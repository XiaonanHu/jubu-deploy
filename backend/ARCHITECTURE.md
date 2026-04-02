# Jubu Backend Architecture

**Last Updated:** 2026-02-06  
**Status:** ✅ Production-Ready

---

## 📊 System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER DEVICE                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Frontend App (Expo/React Native)               │  │
│  │  - Microphone capture                                     │  │
│  │  - LiveKit client connection                              │  │
│  │  - Audio playback                                         │  │
│  └────────────────┬──────────────────────────────────────────┘  │
└──────────────────│──────────────────────────────────────────────┘
                   │
                   │ WebRTC (Audio Streams)
                   │
┌──────────────────▼──────────────────────────────────────────────┐
│                    LIVEKIT SERVER                                │
│  - WebRTC SFU (Selective Forwarding Unit)                       │
│  - Room management                                               │
│  - Track routing                                                 │
│  Port: 7880                                                      │
└──────────────────┬──────────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌───────────────┐     ┌───────────────────────────────────────────┐
│  LIVEKIT API  │     │         LIVEKIT BOT(S)                    │
│               │     │  (One bot instance per conversation)       │
│  FastAPI      │     │                                            │
│  Port: 8001   │     │  ┌──────────────────────────────────┐    │
│               │     │  │   Audio Processing Pipeline        │    │
│  Endpoints:   │     │  │   1. Receive LiveKit audio         │    │
│  - POST /init │     │  │   2. Resample to 16kHz mono        │    │
│  - GET /status│     │  │   3. VAD (Voice Activity Detection)│    │
│  - DELETE     │     │  │   4. Utterance gating              │    │
│               │     │  │   5. Echo suppression              │    │
│  Manages:     │     │  │   6. Persistent STT streaming      │    │
│  - Tokens     │     │  │   7. Publish transcription         │    │
│  - Config     │     │  └──────────────────────────────────┘    │
│               │     │                                            │
│               │     │  Components:                               │
│               │     │  - webrtcvad (VAD)                        │
│               │     │  - resampy (audio resampling)             │
│               │     │  - Google STT (streaming)                 │
│               │     │  - Audio dumping (.recordings/)           │
└───────┬───────┘     └──────────────┬─────────────────────────────┘
        │                            │
        │                            │
        │     ┌──────────────────────┘
        │     │
        ▼     ▼
┌────────────────────────────────────────────────────────────────┐
│                    REDIS (Pub/Sub + KV)                         │
│  - Port: 6379                                                   │
│                                                                  │
│  Channels:                                                       │
│  • conversation_events  - Bot lifecycle (spawn/stop)            │
│  • jubu_tasks          - Transcriptions → Thinker               │
│  • jubu_tts_stream     - TTS chunks → Bot                       │
│  • jubu_tts_events     - TTS lifecycle events                   │
│                                                                  │
│  Keys:                                                           │
│  • conversation:{id}         - Conversation config (hash)       │
│  • room:{room_name}:conversation_id - Room → Conv mapping       │
└────────────────┬───────────────────────────────────────────────┘
                 │
                 │
        ┌────────┴─────────┐
        │                  │
        ▼                  ▼
┌──────────────────┐  ┌─────────────────────────────────────────┐
│  BOT MANAGER     │  │         JUBU THINKER                     │
│                  │  │                                           │
│  Responsibilities│  │  Processing Pipeline:                    │
│  - Listen to     │  │  1. Receive transcription (Redis)        │
│    conversation  │  │  2. Load conversation config             │
│    events        │  │  3. Call LLM (Gemini)                    │
│  - Spawn bot     │  │  4. Generate TTS (ElevenLabs)            │
│    processes     │  │  5. Stream audio chunks to Redis         │
│  - Monitor bot   │  │                                           │
│    health        │  │  Features:                                │
│  - Cleanup on    │  │  - Streaming TTS (low TTFA)              │
│    disconnect    │  │  - Conversation warmup                   │
│                  │  │  - Safety evaluation                     │
└──────────────────┘  │  - Sentence chunking                     │
                      └──────────────────────────────────────────┘
```

---

## 🗂️ File Structure

```
jubu_backend/
│
├── 🌐 API & Entry Points
│   ├── livekit_api.py              # FastAPI server (conversation init)
│   ├── bot_manager.py              # Bot lifecycle manager
│   └── test_full_integration.sh    # Start all services
│
├── 🤖 Bot & Voice Processing
│   ├── livekit_bot.py              # LiveKit bot (VAD + STT)
│   └── jubu_thinker.py             # LLM + TTS processing
│
├── 🎤 Speech Services
│   └── speech_services/
│       ├── speech_to_text/
│       │   ├── __init__.py
│       │   └── providers/
│       │       └── google_stt.py   # Google STT streaming
│       │
│       └── text_to_speech/
│           ├── __init__.py
│           └── providers/
│               └── elevenlabs_tts.py  # ElevenLabs TTS
│
├── 💬 Chat & LLM
│   └── jubu_chat/
│       ├── chat/                   # Conversation logic
│       └── configs/                # Interaction configs
│
├── 🔌 API Adapter
│   └── api_server/
│       └── jubu_adapter.py         # Conversation state management
│
├── 📝 Configuration
│   ├── .env                        # Environment variables
│   └── requirements.txt            # Python dependencies
│
├── 🧪 Testing
│   ├── test_full_integration.sh    # Full backend test
│   ├── run_e2e_test_local.sh      # E2E test
│   └── start_for_device.sh        # Device testing
│
├── 📈 Latency benchmarking
│   └── latency/
│       ├── scripts/run_latency_test.sh   # E2E harness (replay WAVs, P50/P90)
│       ├── scripts/latency_report.py    # Report from turns.jsonl + bot_turns.jsonl
│       ├── test_data/manifest.json      # Utterance list, wav_dir
│       └── runs/<run-name>/              # Per-run outputs (gitignored)
│           ├── turns.jsonl               # Thinker-side timings (when LATENCY_LOG_DIR set)
│           ├── bot_turns.jsonl           # Bot-side timings
│           ├── replay_results.json       # Harness client-side TTFA/E2E
│           └── summary.md                # latency_report.py output
│
├── 📊 Logs & Data
│   ├── .api.log                    # API server logs
│   ├── .thinker.log               # Thinker logs
│   ├── .bot_manager.log           # Bot manager logs
│   ├── .bots.log                  # All bot instances (filtered by room)
│   ├── .recordings/               # Debug audio recordings
│   └── latency/runs/<run>/        # When LATENCY_LOG_DIR set: turns.jsonl, bot_turns.jsonl, etc.
│
└── 📖 Documentation
    ├── ARCHITECTURE.md             # This file
    └── STARTUP_GUIDE.md           # How to start the system

```

---

## 🔄 Data Flow & Workflow

### 1. Conversation Initialization

```
Frontend                API Server               Redis                Bot Manager
   │                         │                     │                       │
   ├─POST /initialize────────>│                     │                       │
   │  {user_id, ...}          │                     │                       │
   │                          │                     │                       │
   │                          ├─Store config────────>│                       │
   │                          │  conversation:{id}  │                       │
   │                          │                     │                       │
   │                          ├─Publish event───────>│                       │
   │                          │  "conversation_     │                       │
   │                          │   initialized"      ├─────────────────────>│
   │                          │                     │  Listen & spawn bot   │
   │<─Response────────────────┤                     │                       │
   │  {token, room_name, ...} │                     │                       │
   │                          │                     │                       │
```

**Key Points:**
- Backend generates: `conversation_id`, `room_name`, `participant_identity`, `token`
- Token valid for 2 hours (configurable)
- Bot auto-spawns before frontend connects

---

### 2. Voice Conversation Flow (Real-Time)

```
User Voice → Frontend → LiveKit → Bot → Redis → Thinker → Redis → Bot → LiveKit → Frontend → User Ears

Detailed breakdown:

┌─────────────┐
│ USER SPEAKS │  Duration: ~0-5s
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  FRONTEND: Mic Capture                      │  Latency: ~20-50ms
│  - OS audio buffer                           │
│  - LiveKit client encoding                   │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  LIVEKIT: WebRTC Transport                  │  Latency: ~20-150ms
│  - Packetization                             │
│  - Network transmission                      │
│  - Jitter buffer                             │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  BOT: Audio Processing (livekit_bot.py)     │  Latency: ~100-600ms
│  1. Receive 48kHz audio frames               │
│  2. Resample to 16kHz mono                   │
│  3. VAD detection:                           │
│     - Start: 80ms voiced audio               │
│     - End: 500ms silence                     │
│  4. Utterance gating:                        │
│     - Min duration: 300ms                    │
│     - Min voiced ratio: 30%                  │
│     - Min RMS: 200.0                         │
│  5. Echo suppression (during bot TTS)       │
│  6. Stream to Google STT (persistent)        │
│  7. Wait for final transcription             │
│     (STT_WAIT_AFTER_VAD_MS: 150ms)          │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  GOOGLE STT: Streaming Recognition          │  Latency: ~300ms-2.5s
│  - Interim results (logged)                  │
│  - Final result                              │
│  - Keepalive during idle                     │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  REDIS: Publish to jubu_tasks               │  Latency: ~1-5ms
│  {                                           │
│    room_name,                                │
│    participant_identity,                     │
│    transcription,                            │
│    duration_ms,                              │
│    stt_latency_s                             │
│  }                                           │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  THINKER: Process Task (jubu_thinker.py)    │  Latency: ~0.6-3s
│  1. Load conversation config                 │
│  2. Initialize conversation if needed        │
│  3. Call LLM (Gemini 2.0 Flash)             │
│  4. Safety evaluation                        │
│  5. Generate TTS response                    │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  ELEVENLABS: Streaming TTS                  │  Latency: ~0.4-1.5s
│  - Sentence chunking                         │
│  - Stream PCM16 16kHz                        │
│  - First chunk (TTFA): ~0.4-1.2s            │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  REDIS: Publish to jubu_tts_stream          │  Latency: ~1-5ms
│  Events:                                     │
│  - stream_start                              │
│  - chunk (audio_b64, seq)                    │
│  - stream_complete                           │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  BOT: TTS Playback (livekit_bot.py)         │  Latency: ~10-50ms
│  1. Resample 16kHz → 48kHz                   │
│  2. Create AudioFrames (20ms chunks)         │
│  3. Publish to LiveKit track "bot-tts"       │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  LIVEKIT: WebRTC Transmission               │  Latency: ~20-150ms
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  FRONTEND: Audio Playback                   │  Latency: ~20-50ms
│  - Decode                                    │
│  - OS audio buffer                           │
│  - Speaker output                            │
└──────┬──────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│ USER HEARS  │
└─────────────┘
```

---

## ⏱️ Latency Breakdown

| Stage | Component | Typical Latency | Notes |
|-------|-----------|-----------------|-------|
| **1. Voice Capture** | Frontend + LiveKit uplink | 50-200ms | Network dependent |
| **2. VAD Processing** | livekit_bot.py | 100-600ms | Depends on speech end detection |
| **3. STT Streaming** | Google STT | 300ms-2.5s | Varies with utterance length |
| **4. LLM Processing** | Gemini 2.0 Flash | 600ms-2s | Depends on response complexity |
| **5. TTS Generation** | ElevenLabs (TTFA) | 400ms-1.2s | First chunk latency |
| **6. TTS Streaming** | ElevenLabs (full) | 1-3s | Total audio generation time |
| **7. Audio Return** | LiveKit downlink + playback | 50-200ms | Network + buffer |
| **TOTAL** | **End-to-End Turn** | **~2-6s** | User stops speaking → Bot starts speaking |

**Optimization Focus Areas:**
1. **VAD End Detection** (500ms silence threshold) - Tunable
2. **STT Wait After VAD** (150ms) - Prevents dropped transcriptions
3. **LLM Call** (600ms-2s) - Prompt optimization, caching
4. **TTS TTFA** (400ms-1.2s) - Sentence chunking helps

---

## 🏗️ Module Details

### 1. `livekit_api.py` - API Server

**Purpose:** HTTP API for conversation lifecycle management

**Key Functions:**
- `initialize_conversation_endpoint()` - Create conversation, generate token
- `get_conversation_status()` - Check conversation state
- `cleanup_conversation()` - End conversation
- `generate_livekit_token()` - JWT token generation

**Dependencies:**
- FastAPI
- Redis (async)
- livekit.api (AccessToken)
- JubuAdapter

**Environment Variables:**
```bash
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
REDIS_URL=redis://localhost
```

---

### 2. `bot_manager.py` - Bot Lifecycle Manager

**Purpose:** Spawn and manage bot processes for conversations

**Key Functions:**
- Listen to `conversation_events` channel
- Spawn subprocess: `python livekit_bot.py` with env vars
- Monitor bot health
- Cleanup on conversation end

**Bot Spawning:**
```python
env = {
    "LIVEKIT_ROOM": room_name,
    "LIVEKIT_IDENTITY": "buju-ai",
    "LIVEKIT_URL": livekit_url,
    "LIVEKIT_API_KEY": api_key,
    "LIVEKIT_API_SECRET": api_secret,
    "STT_PROVIDER": "google",
}
subprocess.Popen(["python", "livekit_bot.py"], env=env)
```

---

### 3. `livekit_bot.py` - Voice Bot (Main Audio Pipeline)

**Purpose:** LiveKit participant that processes voice input and plays TTS output

**Key Classes:**
- `Bot` - Main bot logic
- `ASRState` - VAD state machine (IDLE, IN_UTTERANCE, POST_ROLL)

**Key Methods:**
- `run()` - Connect to LiveKit, publish TTS track
- `_process_audio_stream()` - VAD + STT streaming
- `_run_persistent_stt()` - Persistent Google STT stream
- `_redis_subscriber()` - Listen for TTS chunks
- `_push_tts_chunk()` - Play TTS audio

**Audio Processing Pipeline:**
1. **Receive audio** from LiveKit track (48kHz)
2. **Resample** to 16kHz mono using `resampy`
3. **VAD** using `webrtcvad` (20ms frames)
4. **Utterance gating** - Filter low-quality audio:
   - `MIN_UTTERANCE_MS=300` - Minimum duration
   - `MIN_VOICED_FRAMES=5` - Minimum voiced frames
   - `MIN_VOICED_RATIO=0.3` - Minimum voiced ratio
   - `MIN_UTTERANCE_RMS=200.0` - Minimum audio energy
5. **Echo suppression** - Ignore audio during bot TTS playback
6. **Persistent STT** - Stream to Google continuously
7. **Wait for transcription** - Allow STT results to arrive after VAD ends
8. **Publish to Redis** - Send transcription to thinker

**VAD Configuration:**
```python
START_SPEECH_MS = 80      # 80ms of voice to start
END_SPEECH_MS = 500       # 500ms of silence to end
POST_ROLL_MS = 100        # 100ms post-roll
VAD_AGGRESSIVENESS = 2    # 0-3 (0=permissive, 3=aggressive)
STT_WAIT_AFTER_VAD_MS = 150  # Wait for STT after VAD ends
```

**Debug Features:**
- Audio recording per utterance (`.recordings/` directory)
- Extensive logging (RMS, first frame details)
- WAV file deletion for gated utterances

---

### 4. `jubu_thinker.py` - LLM & TTS Processor

**Purpose:** Process transcriptions, generate responses, stream TTS

**Key Classes:**
- `Thinker` - Main processing loop

**Key Methods:**
- `run()` - Subscribe to `jubu_tasks` channel
- `process_task()` - Process transcription
- `_stream_tts()` - Stream TTS chunks to Redis
- `_warm_conversation()` - Pre-initialize conversations

**Processing Flow:**
1. **Receive transcription** from Redis
2. **Load config** from Redis (conversation:{id})
3. **Initialize conversation** if needed (JubuAdapter)
4. **Call LLM** - `adapter.process_turn_text_only()`
5. **Safety check** - Catch `SafetyEvaluationError`
6. **Generate TTS** - Stream or batch mode
7. **Publish audio** - Stream chunks to Redis

**TTS Streaming:**
- Sentence chunking for lower TTFA
- Base64 encoding
- Sequence numbering
- Stream lifecycle: `stream_start` → `chunk` → `stream_complete`

---

### 5. `speech_services/speech_to_text/providers/google_stt.py`

**Purpose:** Google Cloud Speech-to-Text streaming

**Key Methods:**
- `stream_transcribe()` - Async generator for streaming recognition
- `request_generator()` - Generate streaming requests with keepalive

**Features:**
- Persistent streaming (600s duration limit)
- Interim and final results
- Keepalive mechanism (send silence during idle)
- Cancellation handling with `asyncio.shield`

**Configuration:**
```python
sample_rate_hertz=16000
language_code="en-US"
enable_automatic_punctuation=True
single_utterance=False  # Persistent stream
interim_results=True
```

---

### 6. `api_server/jubu_adapter.py` - Conversation State Manager

**Purpose:** Manage conversation state and service initialization

**Key Methods:**
- `initialize_conversation()` - Create conversation, init services
- `process_turn_text_only()` - Process LLM turn
- `get_stt_service()` - Get STT service for conversation
- `get_tts_service()` - Get TTS service for conversation
- `is_streaming_tts_enabled()` - Check TTS mode
- `cleanup_conversation_resources()` - Cleanup on end

**State Management:**
- Per-conversation STT/TTS service instances
- Conversation history
- Interaction type configuration
- Child profiles

---

## 🚀 Startup Guide

### Prerequisites

1. **LiveKit Server** (running on port 7880)
   ```bash
   livekit-server --dev
   ```

2. **Redis** (running on port 6379)
   ```bash
   redis-server
   ```

3. **Python 3.9+** with dependencies
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment variables** (`.env` file)
   ```bash
   LIVEKIT_URL=ws://127.0.0.1:7880
   LIVEKIT_API_KEY=devkey
   LIVEKIT_API_SECRET=secret
   REDIS_URL=redis://localhost
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ELEVENLABS_API_KEY=your_key
   ```

---

### Quick Start (All Services)

```bash
# In jubu_backend directory
./test_full_integration.sh
```

This script will:
1. ✅ Check dependencies (LiveKit, Redis)
2. 🚀 Start API server (port 8001)
3. 🚀 Start Thinker
4. 🚀 Start Bot Manager
5. ✅ Run validation test
6. 📊 Display status and logs

**Expected Output:**
```
==========================================
  All Backend Services Running! ✅
==========================================

Services:
  API:         http://localhost:8001 (PID: 12345)
  Thinker:     Running (PID: 12346)
  Bot Manager: Running (PID: 12347)

Logs:
  API:         tail -f .api.log
  Thinker:     tail -f .thinker.log
  Bot Manager: tail -f .bot_manager.log
  All Bots:    tail -f .bots.log

✅ Validation passed!
✅ Bot auto-spawned (count: 1)

Backend Ready for Frontend! 🚀
```

---

### Manual Startup (Individual Services)

**Terminal 1: API Server**
```bash
python livekit_api.py
```

**Terminal 2: Thinker**
```bash
python jubu_thinker.py
```

**Terminal 3: Bot Manager**
```bash
python bot_manager.py
```

---

## 🔍 Monitoring & Debugging

### View Logs

```bash
# All logs in real-time
tail -f .api.log .thinker.log .bot_manager.log .bots.log

# Individual services
tail -f .api.log          # API server
tail -f .thinker.log      # LLM + TTS
tail -f .bot_manager.log  # Bot lifecycle
tail -f .bots.log         # Bot instances (filter by room)
```

### Redis Monitoring

```bash
# Watch conversation events
redis-cli SUBSCRIBE conversation_events

# Watch transcriptions
redis-cli SUBSCRIBE jubu_tasks

# Watch TTS stream
redis-cli SUBSCRIBE jubu_tts_stream

# Check active conversations
redis-cli KEYS "conversation:*"
redis-cli HGETALL "conversation:{id}"
```

### Audio Recordings

Debug audio recordings are saved to `.recordings/` directory:
```
.recordings/
  conv_{uuid}_user_{id}_TR_{track_sid}_utt{N}_{timestamp}.wav
```

Enable/disable with:
```bash
export SAVE_LIVEKIT_AUDIO=1  # Enable
export LIVEKIT_AUDIO_DIR=".recordings"  # Directory
export LIVEKIT_AUDIO_MAX_S=10  # Max recording duration (0 = unlimited)
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LIVEKIT_URL` | `ws://127.0.0.1:7880` | LiveKit server URL |
| `LIVEKIT_API_KEY` | `devkey` | LiveKit API key |
| `LIVEKIT_API_SECRET` | `secret` | LiveKit API secret |
| `REDIS_URL` | `redis://localhost` | Redis connection URL |
| `STT_PROVIDER` | `google` | STT provider (google) |
| `TTY_PROVIDER` | `elevenlabs` | TTS provider |
| `VAD_AGGRESSIVENESS` | `2` | VAD sensitivity (0-3) |
| `STT_WAIT_AFTER_VAD_MS` | `150` | Wait for STT after VAD ends |
| `ENABLE_UTTERANCE_GATING` | `1` | Enable utterance quality filtering |
| `MIN_UTTERANCE_MS` | `300` | Minimum utterance duration |
| `MIN_VOICED_FRAMES` | `5` | Minimum voiced frames |
| `MIN_VOICED_RATIO` | `0.3` | Minimum voiced ratio |
| `MIN_UTTERANCE_RMS` | `200.0` | Minimum audio energy |
| `SAVE_LIVEKIT_AUDIO` | `0` | Enable audio recording |
| `LATENCY_LOG_DIR` | `latency/runs` | Where Thinker/Bot write `turns.jsonl`, `bot_turns.jsonl` (set by latency harness) |
| `SAVE_TTS_AUDIO` | `0` | Save TTS WAVs under `LATENCY_LOG_DIR/tts_audio/` (used by harness) |
| `LATENCY_BENCHMARK_DISABLE_SAFETY` | - | When set, benchmark mode disables safety state transitions (harness only) |

---

## 📈 Latency benchmarking

For reproducible per-turn latency runs (TTFA, E2E, stage breakdowns), use the latency harness:

1. **Start backend** (e.g. `./test_full_integration.sh` or run API, Thinker, Bot Manager manually).
2. **Run harness:** `bash latency/scripts/run_latency_test.sh` (optionally `--run-name my-run --limit 3 --chart`).
3. The script sets `LATENCY_LOG_DIR` to `latency/runs/<run-name>/`, starts services if needed, replays WAVs from `latency/test_data/manifest.json`, and runs `latency/scripts/latency_report.py` to produce P50/P90 and `summary.md`.

**Outputs:** `turns.jsonl` (Thinker), `bot_turns.jsonl` (Bot), `replay_results.json` (client-side), `summary.md`. See [latency/README.md](latency/README.md) for manifest format, metrics, and dependencies (e.g. `tools/publish_wav.py`).

---

## 🎯 API Reference

### POST `/initialize_conversation`

Create a new conversation and get LiveKit connection details.

**Request:**
```json
{
  "user_id": "test_user",
  "interaction_type": "chitchat",
  "model": "gemini-2.0-flash",
  "streaming_tts": true,
  "child_id": "optional",
  "child_profile_path": "optional"
}
```

**Response:**
```json
{
  "conversation_id": "abc-123-...",
  "room_name": "conv_abc-123-...",
  "identity": "user_test_user_abc123",
  "token": "eyJhbGc...",
  "ws_url": "ws://192.168.1.10:7880",
  "system_response": "Hi! I'm Buju...",
  "audio_data": "base64...",
  "streaming_tts": true,
  "stt_provider": "google",
  "tts_provider": "elevenlabs"
}
```

### GET `/conversation/{conversation_id}/status`

Check conversation status.

**Response:**
```json
{
  "conversation_id": "abc-123-...",
  "room_name": "conv_abc-123-...",
  "is_active": true,
  "streaming_tts": true,
  "stt_provider": "google",
  "tts_provider": "elevenlabs"
}
```

### DELETE `/conversation/{conversation_id}`

End conversation and cleanup resources.

---

## 🐛 Troubleshooting

### Issue: Bot doesn't spawn

**Check:**
```bash
pgrep -f bot_manager.py  # Is bot manager running?
tail -f .bot_manager.log  # Check for errors
```

**Fix:** Restart bot manager

---

### Issue: No transcription

**Check:**
```bash
grep "STT_STREAM" .bots.log  # Check for STT results
grep "STT_SKIP" .bots.log    # Check for dropped utterances
```

**Common causes:**
- Utterance too short (< 300ms)
- Audio too quiet (RMS < 200)
- VAD ending before STT returns (increase `STT_WAIT_AFTER_VAD_MS`)

---

### Issue: Empty audio recordings

**Check:**
- Is utterance gating enabled? (`ENABLE_UTTERANCE_GATING=1`)
- Are thresholds too aggressive? Try lowering them
- Is background noise triggering VAD? Increase `VAD_AGGRESSIVENESS`

**Fix:**
```bash
export MIN_UTTERANCE_MS=200      # Lower threshold
export MIN_UTTERANCE_RMS=150.0   # Lower threshold
export VAD_AGGRESSIVENESS=3      # More aggressive
```

---

## 📚 Key Design Decisions

### 1. Why Persistent STT Stream?
- Reduces latency (no reconnection overhead)
- Enables interim results during speech
- Better for real-time conversation

### 2. Why Utterance Gating?
- Filters background noise and footsteps
- Prevents empty/low-quality recordings
- Reduces unnecessary LLM calls

### 3. Why Echo Suppression?
- Prevents bot from responding to its own voice
- Grace period based on last TTS chunk duration
- Critical for natural conversation flow

### 4. Why Separate Bot Instances?
- Isolation (one conversation crash doesn't affect others)
- Scalability (distribute across servers)
- Resource management (per-conversation state)

---

## 🚀 Next Steps

**Completed:**
- ✅ LiveKit integration
- ✅ Streaming TTS (low TTFA)
- ✅ Persistent STT
- ✅ Utterance gating
- ✅ Echo suppression
- ✅ Audio debugging tools

**Future Enhancements:**
- [ ] Real-time STT streaming (save 500ms-1s, see archived docs)
- [ ] Speculative LLM processing
- [ ] Neural VAD (Silero)
- [ ] Acoustic Echo Cancellation (AEC)
- [ ] Multi-model inference optimization

---

**Document Owner:** Backend Team  
**Last Reviewed:** 2026-02-06
