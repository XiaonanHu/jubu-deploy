#!/usr/bin/env bash
set -euo pipefail

# Test script for streaming TTS pipeline
# This script starts all services, initializes a conversation with streaming TTS,
# and runs the end-to-end test.

ROOT="/Users/xhu/Dev/jubu_backend"
cd "$ROOT"

# Log files
API_LOG="$ROOT/.api.log"
THINKER_LOG="$ROOT/.thinker.log"
BOT_LOG="$ROOT/.bot.log"

# PIDs
API_PID=""
THINKER_PID=""
BOT_PID=""

# Cleanup function
cleanup() {
  echo ""
  echo "== Cleaning up..."
  [ -n "$API_PID" ] && kill -INT "$API_PID" 2>/dev/null || true
  [ -n "$THINKER_PID" ] && kill -INT "$THINKER_PID" 2>/dev/null || true
  [ -n "$BOT_PID" ] && kill -INT "$BOT_PID" 2>/dev/null || true
  
  # Kill any remaining processes
  pkill -f "livekit_api.py" 2>/dev/null || true
  pkill -f "jubu_thinker.py" 2>/dev/null || true
  pkill -f "livekit_bot.py" 2>/dev/null || true
  
  echo "Cleanup complete."
}

trap cleanup EXIT INT TERM

echo "=========================================="
echo "  Streaming TTS End-to-End Test"
echo "=========================================="
echo ""

# Check dependencies
echo "== Checking dependencies..."

if ! curl -s http://localhost:7880 > /dev/null 2>&1; then
  echo "❌ LiveKit server not running on http://localhost:7880"
  echo "   Please start it: livekit-server --dev"
  exit 1
fi
echo "✅ LiveKit server is running"

if ! redis-cli ping > /dev/null 2>&1; then
  echo "❌ Redis not running on localhost:6379"
  echo "   Please start it: redis-server"
  exit 1
fi
echo "✅ Redis is running"

# Start services
echo ""
echo "== Starting API server..."
python "$ROOT/livekit_api.py" > "$API_LOG" 2>&1 &
API_PID=$!
sleep 2

# Check if API started successfully
if ! curl -s http://localhost:8001/health > /dev/null 2>&1; then
  echo "❌ API server failed to start. Check $API_LOG"
  exit 1
fi
echo "✅ API server started (PID: $API_PID)"

echo ""
echo "== Starting thinker..."
python "$ROOT/jubu_thinker.py" > "$THINKER_LOG" 2>&1 &
THINKER_PID=$!

# Wait for thinker ready signal
wait_time=0
until grep -q "THINKER_READY" "$THINKER_LOG" 2>/dev/null; do
  sleep 0.1
  wait_time=$((wait_time + 1))
  if [ "$wait_time" -gt 150 ]; then
    echo "❌ Thinker timed out. Check $THINKER_LOG"
    exit 1
  fi
done
echo "✅ Thinker ready (PID: $THINKER_PID)"

echo ""
echo "== Starting bot..."
python "$ROOT/livekit_bot.py" > "$BOT_LOG" 2>&1 &
BOT_PID=$!

# Wait for bot ready signal
wait_time=0
until grep -q "BOT_READY" "$BOT_LOG" 2>/dev/null; do
  sleep 0.1
  wait_time=$((wait_time + 1))
  if [ "$wait_time" -gt 150 ]; then
    echo "❌ Bot timed out. Check $BOT_LOG"
    exit 1
  fi
done
echo "✅ Bot ready (PID: $BOT_PID)"

echo ""
echo "== Initializing conversation with streaming TTS and speculation..."
INIT_RESPONSE=$(curl -s -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user", "streaming_tts": true, "speculation_enabled": true, "interaction_type": "chitchat"}')

if echo "$INIT_RESPONSE" | grep -q "conversation_id"; then
  echo "✅ Conversation initialized"
  CONVERSATION_ID=$(echo "$INIT_RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('conversation_id', ''))")
  echo "$INIT_RESPONSE" | python3 -c "
import json, sys
data = json.load(sys.stdin)
filtered = {
    'conversation_id': data.get('conversation_id'),
    'child_id': data.get('child_id'),
    'system_response': data.get('system_response'),
    'interaction_type': data.get('interaction_type'),
    'streaming_tts': data.get('streaming_tts'),
    'speculation_enabled': data.get('speculation_enabled')
}
print(json.dumps(filtered, indent=2))
"
else
  echo "❌ Failed to initialize conversation"
  echo "$INIT_RESPONSE"
  exit 1
fi

if [ -z "$CONVERSATION_ID" ]; then
    echo "❌ Could not extract CONVERSATION_ID from initialization response."
    exit 1
fi

echo ""
echo "== Checking conversation status using ID: $CONVERSATION_ID..."
STATUS=$(curl -s "http://localhost:8001/conversation/$CONVERSATION_ID/status")
echo "$STATUS" | python3 -m json.tool

if printf '%s\n' "$STATUS" | grep -q '"streaming_tts":[[:space:]]*true'; then
  echo "✅ Streaming TTS is enabled"
else
  echo "⚠️  Streaming TTS not enabled, will use batch mode"
fi

if printf '%s\n' "$STATUS" | grep -q '"speculation_enabled":[[:space:]]*true'; then
  echo "✅ Speculation is enabled"
else
  echo "⚠️  Speculation not enabled"
fi

echo ""
echo "== Starting recorder..."
python "$ROOT/tools/record_bot_tts.py" > "$ROOT/.rec.log" 2>&1 &
REC_PID=$!
sleep 1

echo ""
echo "== Publishing test audio..."
python "$ROOT/tools/publish_wav.py" | tee "$ROOT/.pub.log"

echo ""
echo "== Waiting 12s for full pipeline (STT + LLM + streaming TTS)..."
sleep 12

echo ""
echo "== Stopping recorder..."
kill -INT "$REC_PID" 2>/dev/null || true
sleep 1

echo ""
echo "=========================================="
echo "  Test Results"
echo "=========================================="

OUT="$ROOT/tools/bot_response.wav"
if [ -f "$OUT" ]; then
  ls -lh "$OUT"
  echo ""
  echo "== Audio Quality Check =="
  python3 - <<'PYEOF'
import wave
import numpy as np
import sys

wav_path = "/Users/xhu/Dev/jubu_backend/tools/bot_response.wav"
try:
    with wave.open(wav_path, 'rb') as wf:
        frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16)
        rms = np.sqrt(np.mean(audio.astype(np.float32)**2))
        duration = len(audio) / (wf.getframerate() * wf.getnchannels())
        print(f"Duration: {duration:.2f}s")
        print(f"RMS: {rms:.2f}")
        if rms < 100:
            print("⚠️  SILENT - RMS too low")
            sys.exit(1)
        else:
            print("✅ Audio detected!")
except Exception as e:
    print(f"❌ Error reading WAV: {e}")
    sys.exit(1)
PYEOF
  
  echo ""
  echo "== Check for streaming TTS logs =="
  if grep -q "\[TTS_STREAM\]" "$THINKER_LOG"; then
    echo "✅ Streaming TTS was used!"
    grep "\[TTS_STREAM\]" "$THINKER_LOG" | head -5
  else
    echo "⚠️  Batch TTS was used (check logs for why streaming failed)"
  fi
  
  echo ""
  echo "== Check for speculation logs =="
  if grep -q "\[SPECULATION\].*TRIGGERED" "$THINKER_LOG"; then
    echo "✅ Speculation was triggered!"
    grep "\[SPECULATION\]" "$THINKER_LOG" | grep -E "(TRIGGERED|Audio iterator finished)" | head -3
  else
    echo "ℹ️  Speculation not triggered (STT may have returned final result quickly)"
    echo "   This is normal - speculation only triggers when interim is stable AND audio ends before final STT"
  fi
  
  echo ""
  echo "== Latency Analysis =="
  echo "From thinker log:"
  grep "LATENCY" "$THINKER_LOG" | tail -5 || echo "No latency logs found"
  
else
  echo "❌ No output file produced"
  echo ""
  echo "== Bot Log (last 25 lines) =="
  tail -n 25 "$BOT_LOG"
  echo ""
  echo "== Thinker Log (last 25 lines) =="
  tail -n 25 "$THINKER_LOG"
  exit 1
fi

echo ""
echo "=========================================="
echo "  Test Complete!"
echo "=========================================="
echo ""
echo "To play the audio: afplay $OUT"
echo "To check logs:"
echo "  API:     tail -f $API_LOG"
echo "  Thinker: tail -f $THINKER_LOG"
echo "  Bot:     tail -f $BOT_LOG"
echo ""

