#!/usr/bin/env bash
# Start backend configured for device testing

echo "🔍 Auto-detecting LAN IP for device testing..."

# Get LAN IP
LAN_IP=$(ifconfig | grep "inet " | grep -v "127.0.0.1" | grep -E "192\.168\.|172\.20\.|10\." | head -n1 | awk '{print $2}')

if [ -z "$LAN_IP" ]; then
  echo "❌ Could not detect LAN IP. Using localhost (simulator only)."
  export LIVEKIT_URL=ws://127.0.0.1:7880
else
  echo "✅ Detected LAN IP: $LAN_IP"
  export LIVEKIT_URL=ws://$LAN_IP:7880
fi

echo "🚀 Starting backend with LIVEKIT_URL=$LIVEKIT_URL"
echo ""

# Start the backend
./test_full_integration.sh
