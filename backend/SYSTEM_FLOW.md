# Jubu Voice Pipeline - Complete System Flow

**Visual guide to understand the entire voice conversation pipeline**

---

## ⏱️ User-Experienced Latency (Harness TTFA)

**The delay the user actually feels** — from when they stop speaking (publish end) to when they hear the first bot audio — is measured by the latency harness as **TTFA (publish_end → first audio)**.

**Latest run: [`latency/runs/tts_stream_02_25/`](latency/runs/tts_stream_02_25/)**

| Metric | P50 | P90 | N |
|--------|-----|-----|---|
| **TTFA (publish_end → first audio)** | **1530 ms** | **2438 ms** | 28 |
| E2E (publish_start → TTS complete) | 9435 ms | 13242 ms | 30 |

This is the primary metric to optimize for perceived responsiveness. All latency numbers in this doc use **tts_stream_02_25** as the reference run unless noted. See `latency/runs/tts_stream_02_25/summary.md` for the full report.

---

## 🎯 High-Level Flow (One User Turn)

```
┌──────────┐
│   USER   │ "Hello, how are you?"
│  SPEAKS  │
└─────┬────┘
      │ 🎤 Voice (2-5 seconds of speech)
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND (Expo/React Native)                               │
│  • Microphone capture (OS audio API)                        │
│  • LiveKit SDK (WebRTC encoding)                            │
│  • Continuous streaming                                     │
│                                                             │
│  Latency: ~20-50ms (capture + encoding)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │ 🌐 WebRTC audio packets
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  LIVEKIT SFU (Selective Forwarding Unit)                    │
│  • WebRTC transport (UDP/TCP)                               │
│  • Jitter buffer                                            │
│  • Packet loss recovery                                     │
│  • Route to bot participant                                 │
│                                                             │
│  Latency: ~20-150ms (network + jitter buffer)              │
└─────────────────────┬───────────────────────────────────────┘
                      │ 📡 Audio frames (48kHz stereo)
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  LIVEKIT_BOT.PY (Voice Bot Instance)                        │
│                                                             │
│  Step 1: AUDIO RECEPTION                                   │
│  ├─ Receive AudioFrame events from LiveKit track           │
│  └─ First frame log: sample_rate, channels, bytes          │
│                                                             │
│  Step 2: RESAMPLING (self._resample_audio)                 │
│  ├─ Convert stereo → mono (average channels)               │
│  ├─ Resample 48kHz → 16kHz using resampy                   │
│  └─ Output: PCM16 mono 16kHz                               │
│                                                             │
│  Step 3: BUFFERING                                         │
│  ├─ Accumulate bytes in audio_buffer (bytearray)           │
│  └─ Extract 20ms chunks (640 bytes for 16kHz)              │
│                                                             │
│  Step 4: VAD (Voice Activity Detection)                    │
│  ├─ webrtcvad.Vad(aggressiveness=2)                        │
│  ├─ is_speech() check per 20ms frame                       │
│  ├─ State machine:                                         │
│  │   • IDLE: Wait for 80ms voiced audio                    │
│  │   • IN_UTTERANCE: Collect audio, wait for 500ms silence │
│  │   • POST_ROLL: Continue for 100ms, then finalize        │
│  └─ Log: [VAD_START], [VAD_END], [VAD_COMPLETE]           │
│                                                             │
│  Step 5: ECHO SUPPRESSION                                  │
│  ├─ Check if TTS is playing (self.tts_playing)             │
│  ├─ Grace period after TTS ends (last_chunk_duration + 50ms)│
│  └─ Suppress VAD_START during echo period                  │
│                                                             │
│  Step 6: UTTERANCE GATING                                  │
│  ├─ Duration check: ≥ 300ms                                │
│  ├─ Voiced frames: ≥ 5 frames                              │
│  ├─ Voiced ratio: ≥ 30%                                    │
│  ├─ RMS energy: ≥ 200.0                                    │
│  ├─ If fail: [VAD_DROP], delete WAV file                   │
│  └─ If pass: Continue to STT                               │
│                                                             │
│  Step 7: PERSISTENT STT STREAM                             │
│  ├─ Async task: _run_persistent_stt()                      │
│  ├─ Queue-based: push 20ms chunks to asyncio.Queue         │
│  ├─ Google STT: stream_transcribe(audio_generator())       │
│  ├─ Interim results: [STT_STREAM] Google Interim: '...'    │
│  ├─ Final result: [STT_STREAM] Google Final: '...'         │
│  └─ Update shared state: stt_states[participant.sid]       │
│                                                             │
│  Step 8: STT WAIT AFTER VAD                                │
│  ├─ Wait STT_WAIT_AFTER_VAD_MS (default: 150ms)           │
│  ├─ Check for transcription in shared state                │
│  └─ If empty: [STT_SKIP], else: publish to Redis           │
│                                                             │
│  Step 9: PUBLISH TRANSCRIPTION                             │
│  ├─ Redis channel: "jubu_tasks"                            │
│  ├─ Payload: {room_name, participant_identity,             │
│  │            transcription, duration_ms, stt_latency_s}   │
│  └─ Log: [STT_PUBLISHED] 'text' (latency=X.XXs)           │
│                                                             │
│  Step 10: AUDIO RECORDING (if enabled)                     │
│  ├─ WAV file per utterance: .recordings/*.wav              │
│  ├─ Filename: conv_X_user_Y_TR_Z_uttN_timestamp.wav        │
│  └─ Delete file if utterance gated                         │
│                                                             │
│  Latency: VAD + STT; tts_stream_02_25 STT P50 4.7s, P90 8.5s │
└─────────────────────┬───────────────────────────────────────┘
                      │ 📨 Redis Pub/Sub
                      │ Channel: "jubu_tasks"
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  REDIS (Message Broker)                                     │
│  • Pub/Sub channels (jubu_tasks, jubu_tts_stream)          │
│  • Key-value store (conversation config, room mapping)      │
│                                                             │
│  Latency: ~1-5ms (local Redis)                             │
└─────────────────────┬───────────────────────────────────────┘
                      │ 📥 Subscribed
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  JUBU_THINKER.PY (LLM + TTS Processor)                      │
│                                                             │
│  Step 1: RECEIVE TASK                                      │
│  ├─ Redis subscription: pubsub.listen()                    │
│  ├─ Parse message: json.loads(message['data'])             │
│  └─ Log: [THINKER_RECV] ← Received transcription          │
│                                                             │
│  Step 2: LOAD CONFIG                                       │
│  ├─ Get conversation_id from room:X:conversation_id        │
│  ├─ Load config from conversation:{id} hash                │
│  ├─ Extract: streaming_tts, interaction_type, etc.         │
│  └─ Log: [CONFIG] Retrieved from Redis                     │
│                                                             │
│  Step 3: INITIALIZE CONVERSATION                           │
│  ├─ Check: adapter.is_conversation_active()                │
│  ├─ If not: adapter.initialize_conversation()              │
│  ├─ Initialize STT service (not used in this flow)         │
│  ├─ Initialize TTS service (ElevenLabs)                    │
│  └─ Load interaction config, child profile                 │
│                                                             │
│  Step 4: LLM PROCESSING                                    │
│  ├─ Call: adapter.process_turn_text_only(conv_key, text)   │
│  ├─ Conversation history retrieval                         │
│  ├─ Prompt generation (system + user message)              │
│  ├─ LLM call: Gemini 2.0 Flash                             │
│  ├─ Safety evaluation (SafetyEvaluationError check)        │
│  ├─ Response parsing                                       │
│  └─ Log: [LLM_START] → [LLM_COMPLETE] (X.XXs)             │
│                                                             │
│  Step 5: TTS GENERATION (Streaming Mode)                   │
│  ├─ Generate stream_id: {conv_id}-{uuid}                   │
│  ├─ Publish: stream_start event                            │
│  ├─ Sentence chunking: split on .!?\n                      │
│  ├─ Stream to ElevenLabs API                               │
│  ├─ Receive PCM16 16kHz audio chunks                       │
│  ├─ Base64 encode each chunk                               │
│  ├─ Publish: chunk events (seq, audio_b64, bytes)          │
│  ├─ Log first chunk: [TTS_STREAM] First chunk sent        │
│  ├─ Publish: stream_complete event                         │
│  └─ Log: [TTS_COMPLETE] X chunks, Y bytes (Z.ZZs)         │
│                                                             │
│  tts_stream_02_25: LLM P50 765ms, TTS TTFA P50 953ms (P90 1.9s) │
└─────────────────────┬───────────────────────────────────────┘
                      │ 📨 Redis Pub/Sub
                      │ Channel: "jubu_tts_stream"
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  REDIS (Message Broker)                                     │
│  • TTS stream events                                        │
│                                                             │
│  Latency: ~1-5ms (local Redis)                             │
└─────────────────────┬───────────────────────────────────────┘
                      │ 📥 Subscribed
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  LIVEKIT_BOT.PY (TTS Playback)                              │
│                                                             │
│  Step 1: RECEIVE TTS EVENTS                                │
│  ├─ Redis subscription: jubu_tts_stream                    │
│  ├─ Parse events: stream_start, chunk, stream_complete     │
│  └─ Stream queue management (handle multiple streams)       │
│                                                             │
│  Step 2: STREAM ACTIVATION                                 │
│  ├─ Activate stream if current_stream_id is None           │
│  ├─ Buffer chunks if not current stream                    │
│  └─ Publish TTS_START event (echo suppression trigger)     │
│                                                             │
│  Step 3: AUDIO CHUNK PROCESSING                            │
│  ├─ Decode base64 audio chunk                              │
│  ├─ Resample 16kHz → 48kHz (self._resample_pcm16)         │
│  ├─ Calculate chunk duration (for echo grace period)       │
│  ├─ Split into 20ms frames (1920 bytes @ 48kHz)           │
│  └─ Create AudioFrame objects                              │
│                                                             │
│  Step 4: PUBLISH TO LIVEKIT                                │
│  ├─ Call: tts_source.capture_frame(frame)                  │
│  ├─ LiveKit publishes to track "bot-tts"                   │
│  └─ Log: [TTS_PUSH] Chunk pushed (duration, times)        │
│                                                             │
│  Step 5: STREAM FINALIZATION                               │
│  ├─ Receive: stream_complete event                         │
│  ├─ Mark TTS as ended (echo suppression)                   │
│  ├─ Set grace period: last_chunk_duration + 50ms           │
│  ├─ Publish TTS_COMPLETE event                             │
│  └─ Activate next queued stream (if any)                   │
│                                                             │
│  Per-chunk ~10-50ms; tts_stream_02_25 playback P50 2.2s, P90 5.4s │
└─────────────────────┬───────────────────────────────────────┘
                      │ 📡 Audio track "bot-tts"
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  LIVEKIT SFU (Return Path)                                  │
│  • Route from bot to frontend                               │
│  • WebRTC transmission                                      │
│                                                             │
│  Latency: ~20-150ms (network + jitter buffer)              │
└─────────────────────┬───────────────────────────────────────┘
                      │ 🌐 WebRTC audio packets
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND (Playback)                                        │
│  • LiveKit SDK receives track "bot-tts"                     │
│  • WebRTC decoding                                          │
│  • OS audio playback                                        │
│                                                             │
│  Latency: ~20-50ms (decode + playback buffer)              │
└─────────────────────┬───────────────────────────────────────┘
                      │ 🔊 Audio output
                      │
                      ▼
┌──────────┐
│   USER   │ Hears bot response
│  HEARS   │
└──────────┘
```

---

## ⏱️ Complete Latency Breakdown

### End-to-End Turn (User stops speaking → Bot starts speaking)

All numbers below are from **`latency/runs/tts_stream_02_25/`** (latest reference run). Pipeline stage breakdown (P50 / P90):

| # | Stage | Component | tts_stream_02_25 (P50 / P90) | Notes |
|---|-------|-----------|------------------------------|-------|
| 0 | **User Speaking** | Human | 0–5s | Variable speech duration |
| 1 | Frontend Capture | Expo/RN | ~20–50ms | OS audio buffer |
| 2 | Network Uplink | LiveKit | ~20–150ms | WiFi/LTE dependent |
| 3 | VAD + STT | livekit_bot.py + Google STT | **4720 ms / 8540 ms** | Dominant; utterance length dependent |
| 4 | Redis Pub/Sub | Redis | 2 ms / 5 ms | Negligible |
| 5 | LLM Processing | Gemini 2.0 Flash | **765 ms / 1487 ms** | Prompt complexity |
| 6 | TTS Generation (TTFA) | ElevenLabs | **953 ms / 1932 ms** | First audio chunk |
| 7 | TTS total | ElevenLabs | 1584 ms / 3247 ms | Full response |
| 8 | Redis + Bot playback | Redis + livekit_bot.py | Bot playback 2230 ms / 5401 ms | Includes stream handling |
| 9 | Network Downlink + Frontend | LiveKit + Expo/RN | ~40–200ms | Decode + playback buffer |

**User-experienced (Harness TTFA):** **P50 1530 ms, P90 2438 ms** (publish end → first audio at client). This is the main metric; see top of this doc.  
**Harness E2E** (publish start → TTS complete): P50 9435 ms, P90 13242 ms.  
**Backend TTFU** (VAD end → TTS complete, in `turns.jsonl`): P50 1654 ms, P90 3309 ms.

---

## 📊 Latency Optimization Opportunities

(Based on **tts_stream_02_25**: STT is the largest contributor (P50 4.7s), then LLM (P50 765ms) and TTS TTFA (P50 953ms). Goal: reduce **Harness TTFA** P50 1530 ms / P90 2438 ms.)

### 🔴 High Impact (500ms+ savings)
1. **STT** (tts_stream_02_25: P50 4720 ms, P90 8540 ms)
   - Dominant cost. Real-time streaming, speculative processing, or faster endpointing could save 500ms–2s and directly improve user-experienced TTFA.

2. **LLM** (tts_stream_02_25: P50 765 ms, P90 1487 ms)
   - Cached prompts, shorter system prompts, faster models (e.g. Flash). Saves: hundreds of ms.

### 🟡 Medium Impact (100–500ms savings)
3. **TTS TTFA** (tts_stream_02_25: P50 953 ms, P90 1932 ms)
   - Different ElevenLabs model/voice, sentence chunking. Saves: 100–400ms.

4. **VAD tuning** (END_SPEECH_MS 500 → 300ms, POST_ROLL_MS)
   - Tighter endpointing reduces time to STT commit. Risk: more false endpoints. Re-baseline with harness after changes.

5. **Network** (40–300ms)
   - Dedicated servers, jitter buffer tuning. Saves: 20–150ms.

### 🟢 Low Impact (<100ms savings)
6. **Redis** (tts_stream_02_25: ~2 ms)
   - Pipelining, Unix sockets. Saves: 1–2ms.

---

## 🎛️ Tunable Parameters

### In `livekit_bot.py`:
```python
# VAD sensitivity
VAD_AGGRESSIVENESS = 2  # 0=lenient, 3=strict

# Speech detection
START_SPEECH_MS = 80    # Lower = faster detection, more false-positives
END_SPEECH_MS = 500     # Lower = faster response, risk cutting off speech
POST_ROLL_MS = 100      # Additional audio after silence

# STT timing
STT_WAIT_AFTER_VAD_MS = 150  # Wait for STT after VAD ends

# Utterance quality filtering
MIN_UTTERANCE_MS = 300        # Minimum duration
MIN_VOICED_FRAMES = 5         # Minimum voiced frames
MIN_VOICED_RATIO = 0.3        # Minimum 30% voiced
MIN_UTTERANCE_RMS = 200.0     # Minimum audio energy
```

### In `.env`:
```bash
# Model selection (affects LLM latency)
GEMINI_MODEL=gemini-2.0-flash-exp  # Try different models

# TTS settings (affects TTFA)
ELEVENLABS_MODEL_ID=eleven_turbo_v2_5  # Faster model
ELEVENLABS_VOICE_ID=...  # Different voices have different speeds
```

---

## 🔍 Monitoring & Metrics

### Key Logs to Watch

**VAD timing:**
```
[VAD_START] Speech start for user_123
[VAD_END] Speech end for user_123, entering post-roll
[VAD_COMPLETE] Utterance complete (duration=2340ms)
```

**STT latency:**
```
[STT_STREAM] Google Interim: 'hello world'
[STT_STREAM] Google Final: 'hello world'
[STT_PUBLISHED] 'hello world' (latency=1.23s)
```

**LLM + TTS timing:**
```
[LLM_START] → Starting LLM processing at t=123.456
[LLM_COMPLETE] ✓ LLM processing complete (took 0.87s)
[TTS_START] → Starting streaming TTS generation
[TTS_STREAM] First chunk sent (512 bytes)
[TTS_COMPLETE] ✓ Streaming TTS complete (took 1.2s)
```

**End-to-end:**
```
[TASK_COMPLETE] ✅ Total task processing: 2.45s (room=conv_abc)
```

---

## 🏗️ Component Responsibilities Summary

(Latency impact from **tts_stream_02_25**.)

| Component | Primary Role | Latency Impact (tts_stream_02_25) |
|-----------|-------------|-----------------------------------|
| **livekit_bot.py** | Audio I/O + VAD + STT | STT 4720 / 8540 ms; Bot playback 2230 / 5401 ms |
| **jubu_thinker.py** | LLM + TTS generation | LLM 765 / 1487 ms; TTS TTFA 953 / 1932 ms |
| **livekit_api.py** | Conversation management | N/A (initialization only) |
| **bot_manager.py** | Bot lifecycle | N/A (pre-connection) |
| **Redis** | Message broker | ~2 ms per hop |
| **LiveKit** | WebRTC transport | 40–300 ms (network dependent) |
| **Google STT** | Speech recognition | STT 4720 / 8540 ms |
| **ElevenLabs** | TTS generation | TTS TTFA 953 / 1932 ms |

---

## 🎯 Performance Goals

**Current state (from [`latency/runs/tts_stream_02_25/`](latency/runs/tts_stream_02_25/)):**
- **Harness TTFA** (user-experienced: publish end → first audio): **P50 1530 ms, P90 2438 ms** ← primary metric
- **Harness E2E** (publish start → TTS complete): P50 9435 ms, P90 13242 ms
- **Backend TTFU** (VAD end → TTS complete): P50 1654 ms, P90 3309 ms
- STT is the largest stage (P50 4720 ms); LLM P50 765 ms, TTS TTFA P50 953 ms
- ✅ STT streaming with keepalive; ✅ echo suppression

**Future optimizations (if needed):**
- 🎯 Harness TTFA P50 <1530 ms (STT + LLM + TTS and/or model changes)
- 🎯 Real-time speculation: LLM starts during speech

**Reality Check:**
For conversational AI with children, 3-5s latency is often acceptable. Focus on:
1. **Reliability** (no dropped utterances, no crashes)
2. **Quality** (accurate STT, natural TTS)
3. **User experience** (clear feedback, graceful errors)

Optimize latency only if user feedback indicates it's a problem.

---

## 📊 Latency Instrumentation Guide

**Reproducible latency runs:** For P50/P90 and stage breakdowns, use the latency harness: `bash latency/scripts/run_latency_test.sh` (backend must be up). The harness sets `LATENCY_LOG_DIR` so Thinker and Bot write `turns.jsonl` and `bot_turns.jsonl` to the run folder; `latency_report.py` produces `summary.md`. See [latency/README.md](latency/README.md) for usage, manifest, and metrics.

---

### Current Timestamp Coverage

**What You Have:** (see `livekit_bot.py` and `jubu_thinker.py` for implementation)

- ✅ `first_frame_time` - First audio frame from LiveKit
- ✅ `utterance_start_time` - VAD speech start
- ✅ `vad_end_time` - VAD speech end detected
- ✅ `publish_time` - Transcription published to Redis
- ✅ `total_latency` - Bot STT latency (VAD start → publish)
- ✅ `vad_end_to_publish_s` - STT processing time (VAD end → publish)
- ✅ `publish_timestamp` - Wall-clock time for cross-process correlation
- ✅ `task_start_time` - Thinker receives task
- ✅ `redis_latency_ms` - Redis pub/sub latency (Bot → Thinker)
- ✅ `llm_start_time` / `llm_end_time` - LLM processing (Thinker)
- ✅ `tts_start_time` - TTS generation starts
- ✅ `ttfa` - Time To First Audio chunk (first chunk recv - TTS start)
- ✅ `tts_end_time` - TTS generation completes
- ✅ `receive_time` - Bot receives TTS chunk from Redis
- ✅ `push_time` - Bot pushes audio to LiveKit

**What's Missing:**
- ❌ Frontend timestamps (audio received, playback started)
- ❌ LiveKit network latency (internal to LiveKit SFU)

---

### Backend TTFU and structured latency logs

**In code and `turns.jsonl`:** The Thinker writes `dur_backend_ttfu_ms` = **VAD_END → TTS stream complete** (i.e. time from user speech end to full TTS generation done). This is the “backend turn duration” stored in `LATENCY_LOG_DIR/turns.jsonl` and reported as “Backend TTFU” by `latency_report.py`.

**User-experienced latency (Harness TTFA)** is measured by the latency harness from **publish end → first TTS audio at client** and reported as “TTFA (publish_end → first audio)” in `summary.md` and `replay_results.json`. **Latest run tts_stream_02_25: P50 1530 ms, P90 2438 ms** — this is the metric to optimize for perceived responsiveness. For server-side breakdown use the stages in `turns.jsonl` / `bot_turns.jsonl` (STT, Redis, LLM, TTS TTFA, TTS total, Bot playback).

---

### Monitoring Metrics

Create these metrics from your logs:

| Metric | Log Pattern | tts_stream_02_25 |
|--------|-------------|------------------|
| **Harness TTFA** (user-experienced) | `replay_results.json` / `summary.md` “TTFA (publish_end → first audio)” | **P50 1530 ms, P90 2438 ms** |
| **STT** | `dur_stt_ms` in `turns.jsonl` / `[STT_PUBLISHED]` | P50 4720 ms, P90 8540 ms |
| **Redis Latency** | `redis_latency=` in `[THINKER_RECV]` | ~2 ms |
| **LLM Latency** | `dur_llm_ms` in `turns.jsonl` / `[LLM_COMPLETE]` | P50 765 ms, P90 1487 ms |
| **TTS TTFA** | `dur_tts_ttfa_ms` in `turns.jsonl` / `[TTS_TTFA]` | P50 953 ms, P90 1932 ms |
| **TTS Total** | `dur_tts_total_ms` in `turns.jsonl` / `[TTS_COMPLETE]` | P50 1584 ms, P90 3247 ms |
| **Bot Playback** | `bot_dur_tts_playback_ms` in `bot_turns.jsonl` | P50 2230 ms, P90 5401 ms |
| **Backend TTFU** | `dur_backend_ttfu_ms` in `turns.jsonl` (VAD_END → TTS complete) | P50 1654 ms, P90 3309 ms |
| **Harness E2E** | `summary.md` “E2E (publish_start → TTS complete)” | P50 9435 ms, P90 13242 ms |

---

### Example Enhanced Log Output

```
[AUDIO_IN] First frame at t=123.000: sample_rate=48000 channels=2 bytes=3840
[VAD_START] Speech start for user_abc at t=123.456
[VAD_END] Speech end for user_abc at t=125.456, entering post-roll
[STT_PUBLISHED] 'hello world' (latency=3.56s, VAD_END→publish=1.556s)
[THINKER_RECV] ← Received transcription (redis_latency=3.2ms)
[LLM_COMPLETE] ✓ LLM processing complete (took 1.13s)
[TTS_TTFA] ✨ First audio chunk generated in 0.465s (LLM took 1.13s, TTS TTFA=0.465s)
[TTS_PUSH] Chunk pushed: audio_duration=0.512s, total=0.017s
```

**Approx. time to first audio (from logs) = 1.556s (STT) + 0.003s (Redis) + 1.13s (LLM) + 0.465s (TTFA) + 0.017s (playback) = 3.17s.** The stored `dur_backend_ttfu_ms` in `turns.jsonl` is VAD_END → TTS complete (full turn).

---

### Adding Frontend Timestamps

For complete TTFU measurement, add to your frontend:

```typescript
// Track subscribed (bot audio available)
room.on('track_subscribed', (track, publication, participant) => {
  if (participant.identity === 'buju-ai') {
    const audioReceivedTime = performance.now();
    console.log(`[FRONTEND] Bot audio received at ${audioReceivedTime}`);
  }
});

// Playback started (user hears audio)
audioElement.addEventListener('play', () => {
  const playbackStarted = performance.now();
  console.log(`[FRONTEND] Playback started at ${playbackStarted}`);
  
  // Send to backend for correlation
  fetch('/api/log_latency', {
    method: 'POST',
    body: JSON.stringify({
      event: 'audio_playback_started',
      timestamp: playbackStarted,
      room_name: roomName
    })
  });
});
```

---

**See [`ARCHITECTURE.md`](ARCHITECTURE.md) for module details and setup instructions.**

