# 📱 Device Testing Setup Guide

## 🚨 The Problem

Your backend returns `ws://127.0.0.1:7880`, which works for:
- ✅ **Simulator** (shares host loopback)
- ❌ **Real device** (can't reach 127.0.0.1 on your Mac)

**Error on device:**
```
"could not establish signal connection: Network request failed"
```

---

## ✅ Solution: Configure Backend for Device Testing

### **Step 1: Find Your Mac's LAN IP**

```bash
# On macOS:
ifconfig | grep "inet " | grep -v 127.0.0.1

# Example output:
# inet 172.20.10.3 netmask 0xffffff00 broadcast 172.20.10.255
#      ^^^^^^^^^^^^ This is your LAN IP
```

**Common LAN IP ranges:**
- `192.168.x.x` (most home routers)
- `10.x.x.x` (some corporate networks)
- `172.20.x.x` (some hotspots/tethering)

---

### **Step 2: Set LIVEKIT_URL Environment Variable**

**Option A: Export in your shell (temporary)**

```bash
# Replace with YOUR Mac's LAN IP
export LIVEKIT_URL=ws://172.20.10.3:7880

# Then start backend
./test_full_integration.sh
```

**Option B: Create `.env` file (persistent)**

```bash
# Create .env file
cat > .env << 'EOF'
# LiveKit Configuration
LIVEKIT_URL=ws://172.20.10.3:7880  # ⚠️ Replace with YOUR LAN IP
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

# Redis Configuration
REDIS_URL=redis://localhost
EOF

# Then start backend
./test_full_integration.sh
```

**Option C: Modify test script (for testing only)**

```bash
# Edit test_full_integration.sh, add before starting API:
export LIVEKIT_URL=ws://172.20.10.3:7880  # Replace with YOUR LAN IP
```

---

### **Step 3: Verify Backend Returns Correct URL**

```bash
# Start backend
./test_full_integration.sh

# In another terminal, test the API:
curl -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user", "streaming_tts": true}' | python3 -m json.tool

# Check the ws_url field:
# ✅ Should be: "ws_url": "ws://172.20.10.3:7880"
# ❌ NOT:       "ws_url": "ws://127.0.0.1:7880"
```

---

### **Step 4: Ensure LiveKit Server is Reachable**

**Check LiveKit is bound to 0.0.0.0 (not just 127.0.0.1):**

```bash
# Check LiveKit process
ps aux | grep livekit-server

# Should see something like:
# livekit-server --dev
# (--dev mode binds to 0.0.0.0 by default)
```

**Test from your phone's browser:**

1. Open Safari on your iPhone
2. Go to: `http://172.20.10.3:7880` (replace with YOUR LAN IP)
3. You should see a LiveKit response (not a timeout)

**If it times out:**
- Check macOS firewall: System Preferences → Security & Privacy → Firewall
- Allow incoming connections to `livekit-server`
- Or temporarily disable firewall for testing

---

## 🔍 Debugging

### **Check what URL the backend is returning:**

```bash
# Start backend
./test_full_integration.sh

# Test API
curl -s -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "streaming_tts": true}' \
  | python3 -c "import json, sys; print('ws_url:', json.load(sys.stdin)['ws_url'])"

# Expected: ws_url: ws://172.20.10.3:7880
```

---

### **Check LiveKit server logs:**

```bash
# If you started LiveKit manually:
livekit-server --dev

# Look for:
# Starting LiveKit server on :7880
# (no errors about binding)
```

---

### **Check network connectivity from device:**

1. **Ensure phone and Mac are on same WiFi**
2. **Test API reachability from phone:**
   - Open Safari on iPhone
   - Go to: `http://172.20.10.3:8001/health` (replace with YOUR LAN IP)
   - Should see: `{"status":"ok"}`

3. **Test LiveKit reachability from phone:**
   - Open Safari on iPhone
   - Go to: `http://172.20.10.3:7880` (replace with YOUR LAN IP)
   - Should see a LiveKit response

---

## 📋 Quick Checklist

- [ ] Found Mac's LAN IP: `ifconfig | grep "inet " | grep -v 127.0.0.1`
- [ ] Set `LIVEKIT_URL=ws://<YOUR_LAN_IP>:7880`
- [ ] Restarted backend: `./test_full_integration.sh`
- [ ] Verified API returns correct `ws_url` (not 127.0.0.1)
- [ ] Tested LiveKit reachable from phone browser: `http://<YOUR_LAN_IP>:7880`
- [ ] Tested API reachable from phone browser: `http://<YOUR_LAN_IP>:8001/health`
- [ ] Phone and Mac on same WiFi
- [ ] macOS firewall allows LiveKit (port 7880)

---

## 🎯 Frontend's Defensive Fix

Your frontend team added a **defensive rewrite** that replaces `127.0.0.1` with your LAN IP client-side. This is a **good fallback**, but:

**✅ Pros:**
- Works even if backend misconfigured
- Resilient to backend changes

**❌ Cons:**
- Hardcodes LAN IP in frontend (breaks if IP changes)
- Hides backend misconfiguration
- Extra complexity

**Recommendation:**
- **Keep the frontend fix** as a fallback
- **Fix the backend properly** by setting `LIVEKIT_URL` correctly
- This way, both simulator and device work without hacks

---

## 🚀 Production Considerations

### **For Production:**

1. **Use a domain name:**
   ```bash
   LIVEKIT_URL=wss://livekit.yourdomain.com
   ```

2. **Use TLS (wss://):**
   - Required for production
   - iOS requires secure WebSockets in production

3. **Use a reverse proxy:**
   - Nginx or Cloudflare to handle TLS
   - Hide internal ports

4. **Dynamic URL based on request:**
   ```python
   # In livekit_api.py, detect if request is from device vs simulator
   # Return appropriate URL
   ```

---

## 📱 Testing Workflow

### **For Simulator (easy):**
```bash
# Use loopback
export LIVEKIT_URL=ws://127.0.0.1:7880
./test_full_integration.sh
```

### **For Device (requires LAN IP):**
```bash
# Use LAN IP
export LIVEKIT_URL=ws://172.20.10.3:7880  # Replace with YOUR IP
./test_full_integration.sh
```

### **For Both (smart backend):**
```python
# Future enhancement: Backend detects client type and returns appropriate URL
# For now, just use LAN IP for both (works everywhere)
```

---

## ❓ FAQ

### **Q: Why does simulator work but device doesn't?**
**A:** Simulator shares your Mac's loopback (127.0.0.1). Device is on WiFi and needs your Mac's LAN IP.

### **Q: Do I need to restart LiveKit?**
**A:** No, just restart the backend API. LiveKit is already bound to 0.0.0.0.

### **Q: Can I use 0.0.0.0 in LIVEKIT_URL?**
**A:** No. Clients need a specific IP. `0.0.0.0` means "bind to all interfaces" for servers, but clients can't connect to it.

### **Q: What if my LAN IP changes?**
**A:** You'll need to update `LIVEKIT_URL` and restart the backend. For production, use a domain name.

### **Q: Should I commit .env to git?**
**A:** No! Add `.env` to `.gitignore`. Only commit `.env.example` with placeholder values.

---

## 🔗 Related Files

- `livekit_api.py` - Line 150: `livekit_url = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880")`
- `test_full_integration.sh` - Can add `export LIVEKIT_URL=...` at the top
- Frontend: `useConversationEngine.ts` - Has defensive rewrite for 127.0.0.1

---

**TL;DR:** Set `export LIVEKIT_URL=ws://<YOUR_MAC_LAN_IP>:7880` before starting backend. Find your LAN IP with `ifconfig | grep "inet " | grep -v 127.0.0.1`. ✅

