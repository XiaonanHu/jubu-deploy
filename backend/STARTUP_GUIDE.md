# 🚀 Quick Start Guide

**Get the backend running in 3 steps**

> 📖 For detailed architecture, see [`ARCHITECTURE.md`](ARCHITECTURE.md)

---

## Prerequisites

1. **LiveKit Server** (port 7880)
2. **Redis** (port 6379)
3. **Python 3.9+** with dependencies installed
4. **Environment variables** configured (`.env` file)

---

## Start Backend (One Command)

```bash
cd /Users/xhu/Dev/jubu_backend
./test_full_integration.sh
```

This starts:
- API Server (port 8001)
- Thinker (LLM + TTS)
- Bot Manager (bot lifecycle)

**Expected output:**
```
==========================================
  All Backend Services Running! ✅
==========================================

Services:
  API:         http://localhost:8001
  Thinker:     Running
  Bot Manager: Running

✅ Validation passed!
✅ Bot auto-spawned

Backend Ready for Frontend! 🚀
```

---

## Verify Backend

```bash
# Test API
curl http://localhost:8001/health

# Test conversation init
curl -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test"}'

# Check bot spawned
pgrep -f "livekit_bot.py"
```

---

## View Logs

```bash
tail -f .api.log          # API server
tail -f .thinker.log      # LLM + TTS
tail -f .bot_manager.log  # Bot manager
tail -f .bots.log         # All bots (filter by room)
```

---

## Stop Backend

```bash
# Press Ctrl+C in terminal running test_full_integration.sh
# Or manually:
pkill -f "livekit_api.py"
pkill -f "jubu_thinker.py"
pkill -f "bot_manager.py"
pkill -f "livekit_bot.py"
```

---

## Common Issues

### "LiveKit server not running"
```bash
# Start LiveKit in separate terminal
livekit-server --dev
```

### "Redis not running"
```bash
# Start Redis in separate terminal
redis-server
```

### "Bot doesn't spawn"
```bash
# Check bot manager logs
tail -f .bot_manager.log

# Check if bot_manager is running
pgrep -f bot_manager.py
```

### "No transcription"
```bash
# Check bot logs
grep "STT_STREAM\|STT_SKIP" .bots.log

# Common causes:
# - Utterance too short (< 300ms)
# - Audio too quiet (RMS < 200)
# - Background noise (adjust VAD_AGGRESSIVENESS)
```

---

## Development Workflow

### Start infrastructure (once):
```bash
# Terminal 1: LiveKit
livekit-server --dev

# Terminal 2: Redis
redis-server
```

### Start backend (keeps running):
```bash
# Terminal 3: Backend services
./test_full_integration.sh
```

### Restart after code changes:
```bash
# Ctrl+C in Terminal 3, then:
./test_full_integration.sh
```

---

## Configuration

Key environment variables (`.env`):
```bash
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
REDIS_URL=redis://localhost
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
ELEVENLABS_API_KEY=your_key

# Optional tuning
VAD_AGGRESSIVENESS=2              # 0-3 (higher = more aggressive)
STT_WAIT_AFTER_VAD_MS=150         # Wait for STT after speech ends
MIN_UTTERANCE_MS=300              # Minimum utterance duration
MIN_UTTERANCE_RMS=200.0           # Minimum audio energy
SAVE_LIVEKIT_AUDIO=0              # Enable audio recording (1=on)
```

---

## System Architecture

```
Frontend → LiveKit → Bot (VAD + STT) → Redis → Thinker (LLM + TTS) → Redis → Bot → LiveKit → Frontend
```

**Services:**
- **livekit_api.py** - HTTP API for conversation init
- **bot_manager.py** - Spawns bot processes
- **livekit_bot.py** - Voice bot (VAD + STT streaming)
- **jubu_thinker.py** - LLM + TTS processing

**See [`ARCHITECTURE.md`](ARCHITECTURE.md) for detailed flow diagrams and module descriptions.**

---

## API Example

**Initialize conversation:**
```bash
curl -X POST http://localhost:8001/initialize_conversation \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice",
    "interaction_type": "chitchat",
    "streaming_tts": true
  }'
```

**Response:**
```json
{
  "conversation_id": "abc-123...",
  "room_name": "conv_abc-123...",
  "identity": "user_alice_abc123",
  "token": "eyJhbGc...",
  "ws_url": "ws://192.168.1.10:7880",
  "system_response": "Hi! I'm Buju...",
  "streaming_tts": true
}
```

Frontend uses `token` and `room_name` to connect via LiveKit SDK.

---

## Success Criteria

✅ Backend is working when:
1. All services start without errors
2. Validation test passes
3. Bot auto-spawns for test conversation
4. Logs show normal activity

---

**For detailed documentation:**
- Architecture & workflows: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Frontend integration: Ask for CLIENT_LIVEKIT_INTEGRATION_GUIDE.md
- Troubleshooting: See ARCHITECTURE.md "Troubleshooting" section

