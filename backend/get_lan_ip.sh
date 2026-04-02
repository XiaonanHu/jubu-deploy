#!/usr/bin/env bash
# Helper script to get your Mac's LAN IP for device testing

echo "🔍 Finding your Mac's LAN IP..."
echo ""

# Get all non-loopback IPv4 addresses
LAN_IPS=$(ifconfig | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}')

if [ -z "$LAN_IPS" ]; then
  echo "❌ No LAN IP found!"
  echo ""
  echo "Possible reasons:"
  echo "  - Not connected to WiFi"
  echo "  - Using VPN (may hide real IP)"
  echo ""
  exit 1
fi

# Count how many IPs we found
IP_COUNT=$(echo "$LAN_IPS" | wc -l | xargs)

if [ "$IP_COUNT" -eq 1 ]; then
  # Only one IP, use it
  LAN_IP=$(echo "$LAN_IPS" | head -n1)
  echo "✅ Found LAN IP: $LAN_IP"
  echo ""
  echo "To use this for device testing:"
  echo ""
  echo "  export LIVEKIT_URL=ws://$LAN_IP:7880"
  echo "  ./test_full_integration.sh"
  echo ""
  echo "Or add to your shell profile (~/.zshrc or ~/.bashrc):"
  echo ""
  echo "  echo 'export LIVEKIT_URL=ws://$LAN_IP:7880' >> ~/.zshrc"
  echo "  source ~/.zshrc"
  echo ""
else
  # Multiple IPs, let user choose
  echo "⚠️  Found multiple network interfaces:"
  echo ""
  echo "$LAN_IPS" | nl
  echo ""
  echo "Common choices:"
  echo "  - 192.168.x.x  → Home WiFi"
  echo "  - 172.20.x.x   → iPhone hotspot / tethering"
  echo "  - 10.x.x.x     → Corporate network"
  echo ""
  echo "Choose the one that matches your phone's network."
  echo ""
  
  # Try to guess the most likely one (192.168.x.x or 172.20.x.x)
  LIKELY_IP=$(echo "$LAN_IPS" | grep -E "^(192\.168|172\.20)" | head -n1)
  
  if [ -n "$LIKELY_IP" ]; then
    echo "💡 Most likely: $LIKELY_IP"
    echo ""
    echo "To use this:"
    echo ""
    echo "  export LIVEKIT_URL=ws://$LIKELY_IP:7880"
    echo "  ./test_full_integration.sh"
    echo ""
  fi
fi

echo "📱 To test from your phone:"
echo ""
echo "  1. Open Safari on your iPhone"
echo "  2. Go to: http://$LAN_IP:7880"
echo "  3. You should see a LiveKit response (not timeout)"
echo ""
echo "If it times out, check:"
echo "  - Phone and Mac on same WiFi"
echo "  - macOS firewall allows port 7880"
echo "  - LiveKit server is running: livekit-server --dev"
echo ""

