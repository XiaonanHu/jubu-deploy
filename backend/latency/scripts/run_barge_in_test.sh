#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_barge_in_test.sh
#
# Headless barge-in test harness:
#   1. Start all backend services (API, Thinker, Bot Manager)
#   2. Initialize a conversation via the API
#   3. Wait for the bot to connect
#   4. Run tools/test_barge_in.py to execute barge-in scenario(s)
#   5. Print results and clean up
#
# Usage:
#   cd /path/to/jubu_backend
#   bash latency/scripts/run_barge_in_test.sh
#
# Options (env vars):
#   WAV_DIR          Base directory for WAV files (default: ~/backend/harness/LatencySet_v1/audio)
#   DELAY            Seconds to wait after TTS starts before interrupting (default: 1.5)
#   GENERATE_WAVS    If set to "1", generate synthetic WAVs instead of using LatencySet
#   RUN_NAME         Output directory name (default: barge_in_<timestamp>)
#   BARGE_IN_SPEECH_MS  Threshold for barge-in detection in the bot (default: 300)
#   INTERRUPT_LATENCY_THRESHOLD_MS  Max ms from interrupt publish start to tts_interrupted to pass (default: 600)
#
# Single-scenario shortcut:
#   TRIGGER_WAV=/path/to/trigger.wav INTERRUPT_WAV=/path/to/interrupt.wav \
#   bash latency/scripts/run_barge_in_test.sh
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# --- Defaults ---------------------------------------------------------------
RUN_NAME="${RUN_NAME:-barge_in_$(date '+%Y-%m-%d_%H-%M-%S')}"
WAV_DIR="${WAV_DIR:-$HOME/backend/harness/LatencySet_v1/audio}"
GENERATE_WAVS="${GENERATE_WAVS:-0}"
DELAY="${DELAY:-1.5}"
API_PORT=8001
BOT_READY_TIMEOUT=30
MANIFEST="${MANIFEST:-latency/test_data/barge_in/manifest.json}"

# Single-WAV mode (overrides manifest-based multi-scenario run)
TRIGGER_WAV="${TRIGGER_WAV:-}"
INTERRUPT_WAV="${INTERRUPT_WAV:-}"

RUN_DIR="latency/runs/$RUN_NAME"
mkdir -p "$RUN_DIR"

# Load .env if present
if [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi

# Override LiveKit URL to localhost for local testing
export LIVEKIT_URL="ws://localhost:7880"
export LATENCY_LOG_DIR="$RUN_DIR"

# Forward barge-in tuning params to bot process (if set)
if [ -n "${BARGE_IN_SPEECH_MS:-}" ]; then
  export BARGE_IN_SPEECH_MS
fi
if [ -n "${MIN_GAP_BETWEEN_BARGE_IN_S:-}" ]; then
  export MIN_GAP_BETWEEN_BARGE_IN_S
fi
if [ -n "${INTERRUPT_LATENCY_THRESHOLD_MS:-}" ]; then
  export INTERRUPT_LATENCY_THRESHOLD_MS
fi

# --- Helpers ----------------------------------------------------------------
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { log "❌ $*"; exit 1; }

cleanup_pids=""
cleanup() {
  log "== Shutting down services..."
  # shellcheck disable=SC2086
  [ -n "$cleanup_pids" ] && kill $cleanup_pids 2>/dev/null || true
  pkill -f "livekit_bot.py" 2>/dev/null || true
  log "Done."
}
trap cleanup EXIT INT TERM

kill_stale() {
  local pattern="$1" label="$2"
  if pgrep -f "$pattern" > /dev/null 2>&1; then
    log "Killing stale $label processes..."
    pkill -f "$pattern" 2>/dev/null || true
    sleep 1
    pkill -9 -f "$pattern" 2>/dev/null || true
  fi
}

wait_for_string() {
  local logfile="$1" pattern="$2" label="$3" timeout_s="${4:-30}"
  local waited=0
  until grep -q "$pattern" "$logfile" 2>/dev/null; do
    sleep 0.2
    waited=$(echo "$waited + 0.2" | bc)
    if (( $(echo "$waited > $timeout_s" | bc -l) )); then
      log "❌ $label did not become ready within ${timeout_s}s (log: $logfile)"
      return 1
    fi
  done
  log "✅ $label ready (${waited}s)"
}

# --- Pre-flight checks ------------------------------------------------------
log "=========================================="
log "  Jubu Barge-in Test Harness"
log "  Run: $RUN_NAME"
log "=========================================="

if ! curl -s http://localhost:7880 > /dev/null 2>&1; then
  fail "LiveKit server not running on localhost:7880. Start: livekit-server --dev"
fi
log "✅ LiveKit server running"

if ! redis-cli ping > /dev/null 2>&1; then
  fail "Redis not running on localhost:6379. Start: redis-server"
fi
log "✅ Redis running"

# Resolve WAV paths / generation
if [ "$GENERATE_WAVS" = "1" ]; then
  GEN_DIR="$RUN_DIR/test_wavs"
  log "GENERATE_WAVS=1: will generate synthetic WAVs in $GEN_DIR"
  TRIGGER_WAV=""   # will be handled by --generate-wavs flag
  INTERRUPT_WAV="" # will be handled by --generate-wavs flag
else
  if [ -z "$TRIGGER_WAV" ] && [ -z "$INTERRUPT_WAV" ]; then
    # Default: use LatencySet WAVs referenced in manifest
    if [ ! -d "$WAV_DIR" ]; then
      log "⚠️  WAV_DIR not found: $WAV_DIR"
      log "   Either set WAV_DIR or use GENERATE_WAVS=1 for synthetic fallback."
      log "   Using synthetic WAV generation as fallback..."
      GENERATE_WAVS="1"
      GEN_DIR="$RUN_DIR/test_wavs"
    else
      # Parse first scenario from manifest. Trigger uses wav_dir; interrupt uses
      # interrupt_wav_dir if present (e.g. BargeInSet_v1 for no leading silence).
      TRIGGER_WAV="$WAV_DIR/$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
print(m['scenarios'][0]['trigger_file'])
" 2>/dev/null || echo "L01_story_long.wav")"
      INTERRUPT_WAV_DIR=$(python3 -c "
import json, os
m = json.load(open('$MANIFEST'))
d = m.get('interrupt_wav_dir') or m.get('wav_dir')
print(os.path.expanduser(d)) if d else None
" 2>/dev/null)
      [ -z "$INTERRUPT_WAV_DIR" ] && INTERRUPT_WAV_DIR="$WAV_DIR"
      INTERRUPT_WAV="$INTERRUPT_WAV_DIR/$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
print(m['scenarios'][0]['interrupt_file'])
" 2>/dev/null || echo "S01_simple_barge_in.wav")"
      DELAY=$(python3 -c "
import json
m = json.load(open('$MANIFEST'))
print(m['scenarios'][0].get('delay_before_interrupt_s', 1.5))
" 2>/dev/null || echo "1.5")
      log "Using manifest scenario 0: trigger=$TRIGGER_WAV  interrupt=$INTERRUPT_WAV  delay=${DELAY}s"
    fi
  fi
fi

# --- Kill stale processes ---------------------------------------------------
kill_stale "livekit_bot.py"    "livekit bot"
kill_stale "bot_manager.py"    "bot manager"
kill_stale "livekit_api.py"    "LiveKit API"
kill_stale "jubu_thinker.py"   "Thinker"

# --- Start services ---------------------------------------------------------
log "Starting API server..."
python livekit_api.py > "$RUN_DIR/api.log" 2>&1 &
API_PID=$!
cleanup_pids="$API_PID"

api_wait=0
until curl -s "http://localhost:${API_PORT}/health" > /dev/null 2>&1; do
  sleep 0.3
  api_wait=$((api_wait + 1))
  [ "$api_wait" -gt 40 ] && fail "API server did not start. See $RUN_DIR/api.log"
done
log "✅ API server started (PID: $API_PID)"

log "Starting Thinker..."
python jubu_thinker.py > "$RUN_DIR/thinker.log" 2>&1 &
THINKER_PID=$!
cleanup_pids="$cleanup_pids $THINKER_PID"
wait_for_string "$RUN_DIR/thinker.log" "THINKER_READY" "Thinker" 30

log "Starting Bot Manager..."
python bot_manager.py > "$RUN_DIR/bot_manager.log" 2>&1 &
BOT_MGR_PID=$!
cleanup_pids="$cleanup_pids $BOT_MGR_PID"
wait_for_string "$RUN_DIR/bot_manager.log" "BOT_MANAGER_READY" "Bot Manager" 30

# --- Initialize conversation ------------------------------------------------
log "Initializing conversation..."
INIT_RESP=$(curl -s -X POST "http://localhost:${API_PORT}/initialize_conversation" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "barge-in-test", "streaming_tts": true}')

ROOM=$(echo "$INIT_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('room_name',''))" 2>/dev/null || echo "")
[ -z "$ROOM" ] && fail "No room_name in API response: $INIT_RESP"
log "✅ Conversation initialized: room=$ROOM"

# --- Wait for bot to connect ------------------------------------------------
log "Waiting for bot to connect (up to ${BOT_READY_TIMEOUT}s)..."
bot_wait=0
while true; do
  sleep 1
  bot_wait=$((bot_wait + 1))
  if grep -rq "BOT_READY" .bots.log 2>/dev/null; then
    log "✅ Bot ready (${bot_wait}s)"
    break
  fi
  if [ "$bot_wait" -ge "$BOT_READY_TIMEOUT" ]; then
    log "⚠️  Bot may not be ready (timed out), proceeding anyway..."
    break
  fi
done
sleep 2  # give bot a moment to subscribe to tracks

# --- Run barge-in test ------------------------------------------------------
log "Running barge-in test..."
RESULT_FILE="$RUN_DIR/barge_in_result.json"

TEST_ARGS=(
  "--room" "$ROOM"
  "--delay" "$DELAY"
  "--output" "$RESULT_FILE"
)

if [ "$GENERATE_WAVS" = "1" ]; then
  TEST_ARGS+=("--generate-wavs" "${GEN_DIR:-$RUN_DIR/test_wavs}")
else
  TEST_ARGS+=("--trigger-wav" "$TRIGGER_WAV")
  TEST_ARGS+=("--interrupt-wav" "$INTERRUPT_WAV")
fi

TEST_EXIT=0
python tools/test_barge_in.py "${TEST_ARGS[@]}" || TEST_EXIT=$?

# --- Print result summary ---------------------------------------------------
if [ -f "$RESULT_FILE" ]; then
  log ""
  log "Result file: $RESULT_FILE"
  python3 -c "
import json, sys
r = json.load(open('$RESULT_FILE'))
print()
print('=' * 50)
print('  Barge-in Test Summary')
print('=' * 50)
print(f'  Status:              {r.get(\"status\", \"?\").upper()}')
print(f'  Interrupt latency:   {r.get(\"interrupt_latency_ms\", \"N/A\")} ms')
print(f'  Follow-up status:    {r.get(\"follow_up_status\", \"skipped\")}')
if r.get('follow_up_latency_ms'):
    print(f'  Follow-up latency:   {r[\"follow_up_latency_ms\"]} ms')
print('=' * 50)
print()
" 2>/dev/null || true
fi

log "Logs in: $RUN_DIR/"
log "  api.log, thinker.log, bot_manager.log, .bots.log"

if [ "$TEST_EXIT" -eq 0 ]; then
  log "✅ Barge-in test PASSED"
else
  log "❌ Barge-in test FAILED (exit=$TEST_EXIT)"
  exit "$TEST_EXIT"
fi
