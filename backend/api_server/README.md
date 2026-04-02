# api_server

This folder contains the **adapter** used by the production voice stack plus **legacy** standalone server code kept for reference.

**Production voice flow** uses LiveKit (see root [ARCHITECTURE.md](../ARCHITECTURE.md) and [SYSTEM_FLOW.md](../SYSTEM_FLOW.md)). The HTTP API is [livekit_api.py](../livekit_api.py) (port 8001). This folder’s **active** code is:

- **`jubu_adapter.py`** — Bridges the LiveKit/voice stack to KidsChat core ([jubu_chat](../jubu_chat/)) and to STT/TTS ([speech_services](../speech_services/)). Used by `livekit_api.py` (conversation init, config) and `jubu_thinker.py` (turn processing, TTS).

The following are **obsolete** (standalone WebSocket/REST servers replaced by the LiveKit pipeline). They are kept for protocol and design reference only:

- **`obsolete_voice_chat_server.py`** — Former production WebSocket server (VAD, streaming STT/TTS, latency instrumentation).
- **`obsolete_app.py`** — Simpler FastAPI app with REST + WebSocket (file/base64 audio).
- **`obsolete_audio_processor.py`** — File-based audio utilities (used by obsolete_app).

---

## Legacy reference: WebSocket protocol (obsolete_voice_chat_server)

Client → Server:

```json
{ "type": "audio_chunk", "data": { "pcm_b64": "..." } }
{ "type": "text", "data": { "text": "Hello" } }
{ "type": "stop_streaming" }
{ "type": "ping" }
```

Server → Client:

```json
{ "type": "status", "data": { "status": "start_speech" } }
{ "type": "status", "data": { "status": "stop_recording" } }
{ "type": "transcription", "data": { "text": "...", "is_final": false } }
{ "type": "transcription", "data": { "text": "...", "is_final": true } }
{ "type": "audio_stream_start", "data": { "format": "pcm16", "sample_rate": 16000, "channels": 1, "chunk_ms": 200 } }
{ "type": "audio_stream_chunk", "data": { "audio_b64": "...", "seq": 0 } }
{ "type": "audio_stream_end", "data": { "reason": "complete" } }
{ "type": "response", "data": { "system_response": "...", "interaction_type": "...", "tts_streamed": true, "has_audio": true } }
{ "type": "error", "data": { "message": "..." } }
```

Design ideas from the legacy server (non-blocking sender queue, ASR state machine, latency instrumentation, TTS fallback) have been carried over into the LiveKit bot/thinker pipeline where applicable.

---

## Legacy reference: Quick start (obsolete servers)

Only if you need to run the old standalone stack:

```bash
uvicorn api_server.obsolete_voice_chat_server:app --host 0.0.0.0 --port 8000 --reload
```

```bash
curl -X POST http://localhost:8000/initialize_conversation \
  -H 'Content-Type: application/json' \
  -d '{"interaction_type": "chitchat", "model": "google/gemini-2.0-flash", "stt_provider": "google", "tts_provider": "elevenlabs", "streaming_tts": true}'
```

Then connect WebSocket to `/ws/{conversation_id}` and send 20ms PCM16 16k mono frames as base64.

For production, use the LiveKit API and `test_full_integration.sh` as described in the root [README.md](../README.md).
