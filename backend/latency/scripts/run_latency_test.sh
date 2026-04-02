#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_latency_test.sh
#
# End-to-end latency test harness:
#   1. Start all backend services (API, Thinker, Bot Manager)
#   2. Initialize a conversation via the API
#   3. Wait for the bot to spawn and connect
#   4. Run tools/publish_wav.py to replay all utterances in the manifest
#   5. Run latency/scripts/latency_report.py to print the P50/P90 breakdown
#   6. Clean up all services
#
# Usage:
#   cd /path/to/jubu_backend
#   bash latency/scripts/run_latency_test.sh [--run-name baseline]   # or run_2025-02-25_12-00-00 (default)
#                                  [--manifest latency/test_data/manifest.json]
#                                  [--wav-dir <path>]               # default: $HOME/backend/harness/LatencySet_v1/audio
#                                  [--output <path>]                 # default: latency/runs/<run-name>/replay_results.json
#                                  [--chart]
#
# Results are written under latency/runs/<run-name>/ (turns.jsonl, bot_turns.jsonl,
# replay_results.json, summary.md, optional latency_report.png) so runs are comparable.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# --- Default options ---
RUN_NAME="${RUN_NAME:-run_$(date '+%Y-%m-%d_%H-%M-%S')}"
MANIFEST="${MANIFEST:-latency/test_data/manifest.json}"
WAV_DIR="${WAV_DIR:-$HOME/backend/harness/LatencySet_v1/audio}"
CHART_FLAG=""
LIMIT=""
BENCHMARK_MODE=0
API_PORT=8001
BOT_READY_TIMEOUT=30   # seconds to wait for bot to connect after room init

# Parse CLI args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-name)  RUN_NAME="$2";        shift 2 ;;
    --manifest)  MANIFEST="$2";        shift 2 ;;
    --wav-dir)   WAV_DIR="$2";         shift 2 ;;
    --output)    REPLAY_OUTPUT="$2";   shift 2 ;;
    --limit)     LIMIT="$2";           shift 2 ;;
    --benchmark) BENCHMARK_MODE=1;     shift  ;;
    --chart)     CHART_FLAG="--chart"; shift  ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# All outputs for this run go under latency/runs/<run-name>/
RUN_DIR="latency/runs/$RUN_NAME"
mkdir -p "$RUN_DIR"
REPLAY_OUTPUT="${REPLAY_OUTPUT:-$RUN_DIR/replay_results.json}"

# Load .env if present (before harness overrides below)
if [ -f ".env" ]; then
  set -a; source ".env"; set +a
fi
# Thinker and Bot are separate processes; they read LATENCY_LOG_DIR for where to write turns.jsonl, bot_turns.jsonl, tts_audio/
export LATENCY_LOG_DIR="$RUN_DIR"
# Save TTS WAVs per turn under $RUN_DIR/tts_audio/ for quality checks
export SAVE_TTS_AUDIO=1

# Force localhost for LiveKit — .env may have a LAN IP (e.g. for mobile frontend),
# but this script runs everything locally so localhost always works.
export LIVEKIT_URL="ws://localhost:7880"

# Optional benchmark mode:
# - strict replay validation (timeout / invalid TTFA fails run)
# - disable safety state transitions that contaminate long latency sets
# - endpointing-focused settings for faster/stabler STT boundaries
if [ "$BENCHMARK_MODE" -eq 1 ]; then
  export LATENCY_BENCHMARK_DISABLE_SAFETY=1
  export END_SPEECH_MS="${END_SPEECH_MS:-350}"
  export POST_ROLL_MS="${POST_ROLL_MS:-60}"
  export STT_WAIT_AFTER_VAD_MS="${STT_WAIT_AFTER_VAD_MS:-80}"
  export ENABLE_UTTERANCE_GATING="${ENABLE_UTTERANCE_GATING:-0}"
  export MIN_UTTERANCE_RMS="${MIN_UTTERANCE_RMS:-20}"
  echo "[benchmark] strict validation + tuned endpointing + safety-flag suppression"
fi

# ---- Helpers ---------------------------------------------------------------

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

# ---- Pre-flight checks -----------------------------------------------------

log "=========================================="
log "  Jubu Backend Latency Test Harness"
log "=========================================="

if ! curl -s http://localhost:7880 > /dev/null 2>&1; then
  fail "LiveKit server not running on localhost:7880. Start it first: livekit-server --dev"
fi
log "✅ LiveKit server is running"

if ! redis-cli ping > /dev/null 2>&1; then
  fail "Redis not running on localhost:6379. Start it first: redis-server"
fi
log "✅ Redis is running"

if [ ! -f "$MANIFEST" ]; then
  fail "Manifest not found: $MANIFEST"
fi
log "✅ Manifest: $MANIFEST"

if [ ! -d "$WAV_DIR" ]; then
  fail "WAV directory not found: $WAV_DIR"
fi
WAV_COUNT=$(ls "$WAV_DIR"/*.wav 2>/dev/null | wc -l | tr -d ' ')
log "✅ WAV dir: $WAV_DIR ($WAV_COUNT files)"

# ---- Kill stale processes --------------------------------------------------
kill_stale "livekit_bot.py"    "livekit bot"
kill_stale "bot_manager.py"    "bot manager"
kill_stale "livekit_api.py"    "LiveKit API"
kill_stale "jubu_thinker.py"   "Thinker"

# ---- Clear previous run artifacts in RUN_DIR -------------------------------
rm -f "$RUN_DIR/turns.jsonl" "$RUN_DIR/bot_turns.jsonl" 2>/dev/null
rm -rf "$RUN_DIR/tts_audio" 2>/dev/null
log "Cleared previous run artifacts in $RUN_DIR"

# ---- Start services --------------------------------------------------------

log "Starting API server..."
python livekit_api.py > .latency_api.log 2>&1 &
API_PID=$!
cleanup_pids="$API_PID"

api_wait=0
until curl -s "http://localhost:${API_PORT}/health" > /dev/null 2>&1; do
  sleep 0.3
  api_wait=$((api_wait + 1))
  [ "$api_wait" -gt 40 ] && fail "API server did not start. See .latency_api.log"
done
log "✅ API server started (PID: $API_PID)"

log "Starting Thinker..."
python jubu_thinker.py > .latency_thinker.log 2>&1 &
THINKER_PID=$!
cleanup_pids="$cleanup_pids $THINKER_PID"
wait_for_string ".latency_thinker.log" "THINKER_READY" "Thinker" 30

log "Starting Bot Manager..."
python bot_manager.py > .latency_bot_manager.log 2>&1 &
BOT_MGR_PID=$!
cleanup_pids="$cleanup_pids $BOT_MGR_PID"
wait_for_string ".latency_bot_manager.log" "BOT_MANAGER_READY" "Bot Manager" 30

# ---- Initialize conversation -----------------------------------------------

log "Initializing conversation via API..."
INIT_RESP=$(curl -s -X POST "http://localhost:${API_PORT}/initialize_conversation" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "latency-test", "streaming_tts": true}')

ROOM=$(echo "$INIT_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('room_name',''))" 2>/dev/null || echo "")
CONV_ID=$(echo "$INIT_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('conversation_id',''))" 2>/dev/null || echo "")

[ -z "$ROOM" ] && fail "No room_name in API response: $INIT_RESP"
log "✅ Conversation initialized: room=$ROOM conv_id=$CONV_ID"

# ---- Wait for bot to connect -----------------------------------------------

log "Waiting for bot to connect to room $ROOM (up to ${BOT_READY_TIMEOUT}s)..."
bot_wait=0
while true; do
  sleep 1
  bot_wait=$((bot_wait + 1))
  BOT_PROCS=$(pgrep -f "livekit_bot.py" | wc -l | tr -d ' ')
  if [ "${BOT_PROCS:-0}" -ge 1 ]; then
    # Also check that the bot log mentions BOT_READY
    if grep -rq "BOT_READY" .latency_bot_manager.log .bots.log 2>/dev/null; then
      log "✅ Bot is ready (${bot_wait}s)"
      break
    fi
  fi
  if [ "$bot_wait" -ge "$BOT_READY_TIMEOUT" ]; then
    log "⚠️  Bot may not be ready yet (timed out), proceeding anyway..."
    break
  fi
done

# Give bot a moment to subscribe to the room
sleep 2

# ---- Run WAV replay --------------------------------------------------------

log "Running WAV replay..."
LIMIT_ARGS=""
if [ -n "$LIMIT" ]; then
  LIMIT_ARGS="--limit $LIMIT"
fi
BENCHMARK_ARGS=""
if [ "$BENCHMARK_MODE" -eq 1 ]; then
  BENCHMARK_ARGS="--benchmark"
fi
# Capture exit code instead of letting set -e abort immediately.
# This ensures the report is always generated even when benchmark validation fails.
REPLAY_EXIT=0
# shellcheck disable=SC2086
python tools/publish_wav.py \
  --manifest "$MANIFEST" \
  --room "$ROOM" \
  --wav-dir "$WAV_DIR" \
  --output "$REPLAY_OUTPUT" \
  $LIMIT_ARGS \
  $BENCHMARK_ARGS || REPLAY_EXIT=$?

if [ "$REPLAY_EXIT" -eq 0 ]; then
  log "✅ Replay complete. Results: $REPLAY_OUTPUT"
else
  log "⚠️  Replay finished with issues (exit=$REPLAY_EXIT). Generating report anyway..."
fi

# Give latency logs a moment to flush (Thinker/Bot write directly to RUN_DIR)
sleep 1

# ---- Run latency report ----------------------------------------------------

log "Generating latency report..."
REPORT_ARGS="--turns $RUN_DIR/turns.jsonl --bot-turns $RUN_DIR/bot_turns.jsonl"
REPORT_ARGS="$REPORT_ARGS --manifest $MANIFEST"
REPORT_ARGS="$REPORT_ARGS --harness-results $REPLAY_OUTPUT"
REPORT_ARGS="$REPORT_ARGS --markdown $RUN_DIR/summary.md"
if [ "$BENCHMARK_MODE" -eq 1 ]; then
  REPORT_ARGS="$REPORT_ARGS --benchmark-validate"
fi
if [ -n "$CHART_FLAG" ]; then
  REPORT_ARGS="$REPORT_ARGS $CHART_FLAG --chart-output $RUN_DIR/latency_report.png"
fi
# shellcheck disable=SC2086
python "$SCRIPT_DIR/latency_report.py" $REPORT_ARGS || log "⚠️  Report script failed (logs may be empty if no turns completed)"

log "=========================================="
log "  Latency test complete. Run: $RUN_NAME"
log "  Outputs:  $RUN_DIR/"
log "    turns.jsonl, bot_turns.jsonl, replay_results.json, summary.md"
log "    tts_audio/*.wav (when SAVE_TTS_AUDIO=1)"
log "=========================================="

# Propagate replay failure after report is generated
if [ "$REPLAY_EXIT" -ne 0 ]; then
  log "❌ Benchmark FAILED — see issues logged above and in $RUN_DIR/summary.md"
  exit "$REPLAY_EXIT"
fi
