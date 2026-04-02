#!/usr/bin/env bash
set -euo pipefail

# Load environment variables from .env if present
if [ -f ".env" ]; then
  # Export all variables defined in .env for this script
  set -a
  source ".env"
  set +a
fi

# Use localhost for LiveKit in this test. livekit-server --dev binds only to
# 127.0.0.1; if LIVEKIT_URL is a LAN IP (e.g. from .env for a phone), the bot
# would get "Connection refused" because the server is not listening on that IP.
export LIVEKIT_URL="ws://192.168.8.140:7880"  # Slate AX IP address
#export LIVEKIT_URL="ws://172.31.4.97:7880"  # Pixel hotspot IP address
# export LIVEKIT_URL="ws://172.20.10.3:7880"  # Phone hotspot IP address

# Enable gRPC Debugging for Google STT troubleshooting
echo "🔧 Enabling gRPC debugging (GRPC_VERBOSITY=DEBUG, GRPC_TRACE=all)"
# export GRPC_VERBOSITY=DEBUG
# export GRPC_TRACE=all

echo "=========================================="
echo "  Full Backend Integration Test"
echo "=========================================="
echo ""

# Ensure no lingering processes are running
cleanup_processes() {
  local pattern="$1"
  local friendly="$2"

  existing=$(pgrep -f "$pattern" || true)
  if [ -n "$existing" ]; then
    count=$(echo "$existing" | wc -l | tr -d ' ')
    echo "⚠️  Detected $count lingering $friendly process(es) before startup."
    echo "   Attempting to terminate them (SIGTERM, then SIGKILL if needed)..."
    pkill -f "$pattern" 2>/dev/null || true
    sleep 1

    remaining=$(pgrep -f "$pattern" || true)
    if [ -n "$remaining" ]; then
      pkill -9 -f "$pattern" 2>/dev/null || true
      sleep 1

      remaining=$(pgrep -f "$pattern" || true)
      if [ -n "$remaining" ]; then
        remaining_count=$(echo "$remaining" | wc -l | tr -d ' ')
        echo "❌ Could not terminate all $friendly processes (remaining: $remaining_count)."
        echo "   Please investigate (ps -ef | grep \"$pattern\") and rerun the script."
        exit 1
      fi
    fi

    echo "✅ Lingering $friendly processes terminated."
  fi
}

cleanup_processes "livekit_bot.py" "livekit bot"
cleanup_processes "bot_manager.py" "bot manager"
cleanup_processes "livekit_api.py" "LiveKit API"
cleanup_processes "jubu_thinker.py" "Thinker"

# Check dependencies first
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

echo ""
echo "== Starting backend services..."

# 1. Start API server
echo "Starting API server..."
python livekit_api.py > .api.log 2>&1 &
API_PID=$!
sleep 2

# Wait for API to be ready
health_check_attempts=0
until curl -s http://localhost:8001/health > /dev/null 2>&1; do
  sleep 0.5
  health_check_attempts=$((health_check_attempts + 1))
  if [ "$health_check_attempts" -gt 10 ]; then
    echo "❌ API server failed to start. Check .api.log"
    kill $API_PID 2>/dev/null || true
    exit 1
  fi
done
echo "✅ API server started (PID: $API_PID)"

# 2. Start Thinker
echo "Starting Thinker..."
python jubu_thinker.py > .thinker.log 2>&1 &
THINKER_PID=$!

# Wait for thinker ready signal
wait_time=0
until grep -q "THINKER_READY" .thinker.log 2>/dev/null; do
  sleep 0.1
  wait_time=$((wait_time + 1))
  if [ "$wait_time" -gt 150 ]; then
    echo "❌ Thinker timed out. Check .thinker.log"
    kill $API_PID $THINKER_PID 2>/dev/null || true
    exit 1
  fi
done
echo "✅ Thinker ready (PID: $THINKER_PID)"

# 3. Start Bot Manager
echo "Starting Bot Manager..."
python bot_manager.py > .bot_manager.log 2>&1 &
BOT_MANAGER_PID=$!

# Wait for bot manager ready signal
wait_time=0
until grep -q "BOT_MANAGER_READY" .bot_manager.log 2>/dev/null; do
  sleep 0.1
  wait_time=$((wait_time + 1))
  if [ "$wait_time" -gt 150 ]; then
    echo "❌ Bot Manager timed out. Check .bot_manager.log"
    kill $API_PID $THINKER_PID $BOT_MANAGER_PID 2>/dev/null || true
    exit 1
  fi
done
echo "✅ Bot Manager ready (PID: $BOT_MANAGER_PID)"

echo ""
echo "=========================================="
echo "  All Backend Services Running! ✅"
echo "=========================================="
echo ""
echo "Services:"
echo "  API:         http://localhost:8001 (PID: $API_PID)"
echo "  Thinker:     Running (PID: $THINKER_PID)"
echo "  Bot Manager: Running (PID: $BOT_MANAGER_PID)"
echo ""
echo "Logs:"
echo "  API:         tail -f .api.log"
echo "  Thinker:     tail -f .thinker.log"
echo "  Bot Manager: tail -f .bot_manager.log"
echo "  All Bots:    tail -f .bots.log   (all bot instances, filter by room_name)"
echo ""

# Run quick validation test
echo "== Running validation test..."
# In DEMO_MODE=1, the backend will override user_id and child_id with DEMO values.
RESPONSE=$(curl -s -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{"user_id": "integration_test", "streaming_tts": true}')

TOKEN=$(echo "$RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('token', ''))" 2>/dev/null || echo "")
ROOM=$(echo "$RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('room_name', ''))" 2>/dev/null || echo "")
WS_URL=$(echo "$RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('ws_url', ''))" 2>/dev/null || echo "")
IDENTITY=$(echo "$RESPONSE" | python3 -c "import json, sys; print(json.load(sys.stdin).get('identity', ''))" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  echo "❌ VALIDATION FAILED: No token in response"
  echo "Response:"
  echo "$RESPONSE" | python3 -m json.tool
  echo ""
  echo "Backend services are running but API may have issues."
  echo "Check .api.log for errors."
else
  echo "✅ Validation passed!"
  echo "   WS URL:   $WS_URL"
  echo "   Room:     $ROOM"
  echo "   Identity: $IDENTITY"
  echo "   Token:    ${TOKEN:0:30}..."
  
  # Wait for bot to spawn
  sleep 3
  BOT_COUNT=$(pgrep -f "livekit_bot.py" 2>/dev/null | wc -l | tr -d ' \n' || echo "0")
  
  if [ "$BOT_COUNT" -eq 1 ]; then
    echo "✅ Bot auto-spawned (count: $BOT_COUNT)"
  elif [ "$BOT_COUNT" -gt 1 ]; then
    echo "❌ Detected $BOT_COUNT livekit_bot.py processes after startup (expected 1)."
    echo "   Shutting down services. Please inspect .bot_manager.log and running processes."
    kill $API_PID $THINKER_PID $BOT_MANAGER_PID 2>/dev/null || true
    pkill -f "livekit_bot.py" 2>/dev/null || true
    exit 1
  else
    echo "⚠️  No bot process detected (count: $BOT_COUNT)"
    echo "   Bot may have failed to start. Checking logs..."
    
    # Check if there are errors in bot log
    if [ -f ".bots.log" ]; then
      BOT_ERRORS=$(grep -i "error\|failed\|exception" .bots.log | tail -3 || echo "")
      if [ -n "$BOT_ERRORS" ]; then
        echo "   ❌ Found errors in .bots.log:"
        echo "$BOT_ERRORS" | sed 's/^/      /'
      fi
    fi
    
    # Check bot manager log
    if [ -f ".bot_manager.log" ]; then
      MGR_ERRORS=$(grep -i "error\|failed" .bot_manager.log | tail -3 || echo "")
      if [ -n "$MGR_ERRORS" ]; then
        echo "   ❌ Found errors in .bot_manager.log:"
        echo "$MGR_ERRORS" | sed 's/^/      /'
      fi
    fi
    
    echo "   For full details: tail -f .bots.log .bot_manager.log"
  fi
fi

echo ""
echo "=========================================="
echo "  Backend Ready for Frontend! 🚀"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Keep this terminal running (backend services)"
echo "  2. In your frontend directory, run:"
echo "     npx expo start"
echo "     (then press 'i' for iOS simulator)"
echo ""
echo "To stop backend: Press Ctrl+C"
echo ""

# Cleanup function — shuts down backend services
cleanup() {
  echo ""
  echo "== Shutting down backend services..."
  kill $API_PID $THINKER_PID $BOT_MANAGER_PID 2>/dev/null || true
  pkill -f "livekit_bot.py" 2>/dev/null || true
  echo "Backend stopped."
}
trap cleanup EXIT INT TERM

# Keep services running
echo "Backend services running. Press Ctrl+C to stop."
wait