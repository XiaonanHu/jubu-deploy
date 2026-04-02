import asyncio
import base64
import json
import logging
import os
import signal
import time
import uuid
import wave
from collections import deque
from enum import Enum
from pathlib import Path

import numpy as np
import redis.asyncio as redis
import resampy
import webrtcvad
from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants
from livekit.rtc import (
    AudioFrame,
    AudioSource,
    AudioStream,
    LocalAudioTrack,
    Participant,
    Room,
    Track,
    TrackKind,
    TrackPublication,
    TrackSource,
)

# Import STT service for real-time streaming
from speech_services.speech_to_text import initialize_stt_service

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- Constants ---
FRAME_MS = 20
LATENCY_LOG_DIR = Path(os.getenv("LATENCY_LOG_DIR", "latency/runs"))
CONVERSATION_LATENCY_LOG_DIR = Path(
    os.getenv("CONVERSATION_LATENCY_LOG_DIR", "logs/latency/conversation_logs")
)
ENABLE_CONVERSATION_LATENCY_JSON_LOGGING = (
    os.getenv("ENABLE_CONVERSATION_LATENCY_JSON_LOGGING", "1") == "1"
)
DEBUG_LOG_PATH = Path(__file__).resolve().parent / ".cursor" / "debug-ffe215.log"


def _debug_log(message: str, data: dict, hypothesis_id: str, location: str = ""):
    """Append one NDJSON line to the session debug log (for STT truncation debugging)."""
    try:
        payload = {
            "sessionId": "ffe215",
            "hypothesisId": hypothesis_id,
            "location": location or "livekit_bot",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def _append_jsonl(filepath: Path, record: dict) -> None:
    """Append a JSON record as a new line to a JSONL file (thread-safe for single-process use)."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        logging.error("[JSONL] Failed to write %s: %s", filepath, exc)


# Input (captured audio → VAD/STT) sample rate
INPUT_SAMPLE_RATE = 16000
INPUT_FRAME_BYTES = (
    INPUT_SAMPLE_RATE * 1 * 2 * FRAME_MS // 1000
)  # 640 bytes for 16k mono 16-bit

# Output (TTS → LiveKit) sample rate. Match ElevenLabs native PCM output (pcm_16000)
# so no resampling is needed — resampling each small chunk independently with
# resampy caused hard discontinuities and injected silence at every boundary.
# LiveKit's WebRTC stack on the receiving device handles any internal upsampling.
OUTPUT_SAMPLE_RATE = 16000
OUTPUT_FRAME_BYTES = (
    OUTPUT_SAMPLE_RATE * 1 * 2 * FRAME_MS // 1000
)  # 640 bytes for 16k mono 16-bit

# VAD Parameters
START_SPEECH_MS = int(os.getenv("START_SPEECH_MS", "80"))
END_SPEECH_MS = int(os.getenv("END_SPEECH_MS", "300"))
POST_ROLL_MS = int(os.getenv("POST_ROLL_MS", "50"))
VAD_AGGRESSIVENESS = int(os.getenv("VAD_AGGRESSIVENESS", "2"))
STT_WAIT_AFTER_VAD_MS = int(os.getenv("STT_WAIT_AFTER_VAD_MS", "150"))

# Barge-in Parameters
# Higher than START_SPEECH_MS to avoid false positives from background noise during TTS.
BARGE_IN_SPEECH_MS = int(os.getenv("BARGE_IN_SPEECH_MS", "500"))
# Minimum time between consecutive barge-in events to prevent rapid re-triggering.
MIN_GAP_BETWEEN_BARGE_IN_S = float(os.getenv("MIN_GAP_BETWEEN_BARGE_IN_S", "1.5"))
# Minimum average RMS energy of the voiced run before a barge-in is accepted.
# TTS echo leaking through the phone mic typically has RMS 2-20, while real
# child speech is 200+.  This gate prevents echo-triggered false barge-ins.
BARGE_IN_MIN_RMS = float(os.getenv("BARGE_IN_MIN_RMS", "150"))
# Grace period after the first TTS audio frame is pushed before barge-in
# detection is armed.  Must be long enough for the phone's AEC to converge
# after the speaker starts playing (~1-2 s round-trip including network).
BARGE_IN_COOLDOWN_MS = int(os.getenv("BARGE_IN_COOLDOWN_MS", "1500"))
# Minimum RMS coefficient of variation (std/mean) in the voiced run.
# Flat energy (low CV) suggests background noise; real speech has higher variance.
BARGE_IN_MIN_RMS_CV = float(os.getenv("BARGE_IN_MIN_RMS_CV", "0.3"))
# Minimum peak-to-mean RMS ratio in the voiced run.
# Near-field speech has sharp peaks; far-field/ambient noise is flatter.
BARGE_IN_MIN_PEAK_RATIO = float(os.getenv("BARGE_IN_MIN_PEAK_RATIO", "1.5"))


class ASRState(Enum):
    IDLE = 1
    IN_UTTERANCE = 2
    POST_ROLL = 3


class Bot:
    def __init__(
        self, url: str, api_key: str, api_secret: str, stt_provider: str = "google"
    ):
        self.livekit_url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.room: Room | None = None  # Will be created in run()
        self.tts_source: AudioSource | None = None
        self.redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost"))
        self.processing_tasks = {}  # Store a task per participant
        self.active_track_sids: set[str] = set()
        self.current_stream_id: str | None = None
        self.tts_stream_queue: deque[str] = deque()
        self.tts_stream_buffers: dict[str, deque[bytes]] = {}
        self.tts_stream_metadata: dict[str, dict[str, int]] = {}
        # Echo suppression: track when TTS is playing to avoid processing echoed audio
        self.tts_playing: bool = False
        self.tts_end_time: float = 0.0  # Timestamp when TTS ended
        self.last_chunk_duration_s: float = (
            0.5  # Duration of last TTS chunk (for grace period)
        )
        # Carry-over buffer: partial PCM frame bytes from the previous _push_tts_chunk call.
        # This prevents zero-padding discontinuities at chunk boundaries.
        self._tts_leftover: bytes = b""

        # Barge-in state
        self.barge_in_count: int = 0
        self.last_barge_in_ts: float = 0.0
        self.tts_cancelled_at_ts: float | None = None
        # Rolling mean RMS during TTS playback (for dynamic barge-in threshold)
        self._tts_window_rms_mean: float = 0.0
        # Monotonic timestamp of first actual audio frame pushed to LiveKit for
        # the current TTS stream.  Used for barge-in cooldown so the timer
        # starts from real audio output, not the earlier stream_start signal.
        self._tts_first_audio_push_mono: float = 0.0

        # Shared state for persistent STT
        # Structure: { participant_sid: {"text": str, "last_update": float} }
        self.stt_states = {}

        # Store STT config for lazy initialization
        self.stt_provider = stt_provider
        self.stt_service = None
        self.save_audio_enabled = os.getenv("SAVE_LIVEKIT_AUDIO", "0") == "1"
        self.save_audio_dir = Path(os.getenv("LIVEKIT_AUDIO_DIR", ".recordings"))
        self.save_audio_max_s = float(os.getenv("LIVEKIT_AUDIO_MAX_S", "0"))
        self.enable_utterance_gating = os.getenv("ENABLE_UTTERANCE_GATING", "1") == "1"
        self.min_utterance_ms = int(os.getenv("MIN_UTTERANCE_MS", "300"))
        self.min_voiced_frames = int(os.getenv("MIN_VOICED_FRAMES", "5"))
        self.min_voiced_ratio = float(os.getenv("MIN_VOICED_RATIO", "0.3"))
        self.min_utterance_rms = float(os.getenv("MIN_UTTERANCE_RMS", "200.0"))
        self.stt_wait_after_vad_ms = STT_WAIT_AFTER_VAD_MS

    async def _initialize_stt(self):
        """Initialize STT service inside the running event loop."""
        if self.stt_service:
            return

        logging.info(f"Initializing STT service with provider: {self.stt_provider}")
        service, success = initialize_stt_service(
            provider_name=self.stt_provider, language_code="en"
        )
        if not success or service is None:
            error_msg = (
                f"Failed to initialize STT service with provider: {self.stt_provider}"
            )
            logging.error(f"❌ {error_msg}")
            raise RuntimeError(error_msg)

        self.stt_service = service
        logging.info(f"✅ Initialized STT service with provider: {self.stt_provider}")

    def _should_process_publication(
        self, publication: TrackPublication, participant: Participant
    ) -> bool:
        """Return True when the remote audio publication should be processed for STT."""
        if publication.kind != TrackKind.KIND_AUDIO:
            return False
        if participant.identity == self.identity:
            return False
        if getattr(publication, "name", "") == "bot-tts":
            logging.debug("Ignoring bot-tts track from %s", participant.identity)
            return False

        source = getattr(publication, "source", None)
        if source is not None:
            # Prefer explicit LiveKit enums when available, but fall back to name check.
            microphone_source = getattr(TrackSource, "SOURCE_MICROPHONE", None)
            speaker_source = getattr(TrackSource, "SOURCE_SPEAKER", None)
            screen_audio_source = getattr(
                TrackSource, "SOURCE_SCREEN_SHARE_AUDIO", None
            )

            disallowed_sources = {speaker_source, screen_audio_source}
            if microphone_source is not None:
                disallowed_sources.discard(microphone_source)

            if source in disallowed_sources:
                logging.info(
                    "Skipping non-microphone audio track '%s' (source=%s) from %s",
                    getattr(publication, "name", "unknown"),
                    source,
                    participant.identity,
                )
                return False

            source_name = str(source).lower()
            if "speaker" in source_name or "screen" in source_name:
                logging.info(
                    "Skipping secondary audio track '%s' (source=%s) from %s",
                    getattr(publication, "name", "unknown"),
                    source,
                    participant.identity,
                )
                return False

        return True

    async def _publish_tts_start(self, stream_id: str) -> None:
        self.tts_playing = True
        self._tts_first_audio_push_mono = 0.0
        logging.info(f"[TTS_START] TTS playback started (barge-in detection active)")
        turn_id = self.tts_stream_metadata.get(stream_id, {}).get("turn_id")
        await self.redis_client.publish(
            "jubu_tts_events",
            json.dumps(
                {
                    "event": "tts_start",
                    "room_name": self.room.name if self.room else "",
                    "stream_id": stream_id,
                    "turn_id": turn_id,
                    "event_ts": time.time(),
                }
            ),
        )

    async def _handle_barge_in(
        self, participant_identity: str, voiced_run_ms: int = 0
    ) -> None:
        """Stop TTS playback immediately when the user speaks over the bot."""
        interrupted_stream = self.current_stream_id
        self.barge_in_count += 1
        self.last_barge_in_ts = time.monotonic()
        self.tts_cancelled_at_ts = time.time()

        logging.info(
            "[BARGE_IN] Triggered by %s, voiced_ms=%d, stream_id=%s, count=%d",
            participant_identity,
            voiced_run_ms,
            interrupted_stream,
            self.barge_in_count,
        )

        # 1. Stop playback state immediately (hard stop — no fade-out)
        self.tts_playing = False
        self.current_stream_id = None
        self._tts_leftover = b""

        # 2. Flush all queued/buffered TTS streams
        self.tts_stream_queue.clear()
        self.tts_stream_buffers.clear()
        self.tts_stream_metadata.clear()

        logging.info("[BARGE_IN] Playback stopped, buffers flushed")

        # 3. Signal Thinker to cancel ongoing LLM+TTS generation
        #    (Phase 1: Thinker ignores this; Phase 2: Thinker acts on it)
        try:
            await self.redis_client.publish(
                "jubu_interrupt",
                json.dumps(
                    {
                        "room_name": self.room.name if self.room else "",
                        "stream_id": interrupted_stream,
                        "event_ts": time.time(),
                    }
                ),
            )
        except Exception as exc:
            logging.warning("[BARGE_IN] Failed to publish interrupt signal: %s", exc)

        # 4. Emit tts_interrupted event on jubu_tts_events for test harness measurement
        try:
            await self.redis_client.publish(
                "jubu_tts_events",
                json.dumps(
                    {
                        "event": "tts_interrupted",
                        "room_name": self.room.name if self.room else "",
                        "stream_id": interrupted_stream,
                        "barge_in_count": self.barge_in_count,
                        "event_ts": time.time(),
                    }
                ),
            )
        except Exception as exc:
            logging.warning(
                "[BARGE_IN] Failed to publish tts_interrupted event: %s", exc
            )

        logging.info("[BARGE_IN] Interrupt events published")

    async def _finalize_stream(self, stream_id: str) -> None:
        # Flush any partial frame left from the last _push_tts_chunk call.
        # This is the only place zero-padding is acceptable — it is at most
        # OUTPUT_FRAME_BYTES-1 bytes (< 20ms) at the very tail of the stream.
        if self._tts_leftover and self.tts_source is not None:
            pad_len = OUTPUT_FRAME_BYTES - len(self._tts_leftover)
            padded = self._tts_leftover + b"\x00" * pad_len
            frame = AudioFrame(
                data=padded,
                sample_rate=OUTPUT_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=OUTPUT_FRAME_BYTES // 2,
            )
            await self.tts_source.capture_frame(frame)
            logging.info(
                f"[TTS_FLUSH] Flushed {len(self._tts_leftover)}B leftover (+{pad_len}B pad) at stream end"
            )
            self._tts_leftover = b""

        meta = self.tts_stream_metadata.get(stream_id, {})
        total_bytes = meta.get("total_bytes", 0)
        chunks = meta.get("chunks", 0)
        logging.info(
            f"[TTS_STREAM] Complete: {chunks} chunks, {total_bytes} bytes stream_id={stream_id}"
        )

        # Mark TTS as ended (will suppress STT for grace period based on last chunk duration)
        self.tts_playing = False
        self.tts_end_time = time.monotonic()
        # Add a small buffer (50ms) to account for system latency
        grace_period = self.last_chunk_duration_s + 0.05
        logging.info(
            f"[TTS_SUPPRESS] TTS playback ended, will suppress STT for {grace_period:.3f}s grace period "
            f"(last_chunk={self.last_chunk_duration_s:.3f}s)"
        )

        # Emit structured bot turn summary for latency analysis
        ts_first_recv = meta.get("ts_first_chunk_recv")
        ts_first_pushed = meta.get("ts_first_chunk_pushed")
        ts_last_pushed = meta.get("ts_last_chunk_pushed")
        anchor_ts = meta.get("anchor_ts")
        dur_playback_ms = (
            round((ts_last_pushed - ts_first_pushed) * 1000)
            if ts_first_pushed and ts_last_pushed
            else None
        )
        dur_user_perceived_ttfa_ms = (
            round((ts_first_pushed - anchor_ts) * 1000)
            if ts_first_pushed and isinstance(anchor_ts, (int, float))
            else None
        )
        bot_summary = {
            "event": "bot_turn_summary",
            "turn_id": meta.get("turn_id", stream_id[:8]),
            "stream_id": stream_id,
            "conversation_id": meta.get("conversation_id"),
            "ttfa_anchor_ts": anchor_ts,
            "ttfa_anchor_name": meta.get("anchor_name"),
            "ts_first_tts_chunk_recv": ts_first_recv,
            "ts_first_tts_chunk_pushed": ts_first_pushed,
            "ts_last_tts_chunk_pushed": ts_last_pushed,
            "dur_tts_playback_ms": dur_playback_ms,
            "dur_user_perceived_ttfa_ms": dur_user_perceived_ttfa_ms,
        }
        _append_jsonl(LATENCY_LOG_DIR / "bot_turns.jsonl", bot_summary)
        if ENABLE_CONVERSATION_LATENCY_JSON_LOGGING and meta.get("conversation_id"):
            _append_jsonl(
                CONVERSATION_LATENCY_LOG_DIR
                / str(meta.get("conversation_id"))
                / "bot_turns.jsonl",
                bot_summary,
            )
        logging.info(
            "[BOT_TURN] Logged turn_id=%s playback=%sms",
            bot_summary["turn_id"],
            dur_playback_ms,
        )

        await self.redis_client.publish(
            "jubu_tts_events",
            json.dumps(
                {
                    "event": "tts_complete",
                    "room_name": self.room.name if self.room else "",
                    "stream_id": stream_id,
                    "turn_id": meta.get("turn_id"),
                    "total_bytes": total_bytes,
                    "chunks": chunks,
                    "event_ts": time.time(),
                }
            ),
        )

        # Remove from queue (safely handle if already removed)
        try:
            self.tts_stream_queue.remove(stream_id)
        except ValueError:
            pass  # Already removed or never queued

        self.tts_stream_buffers.pop(stream_id, None)
        self.tts_stream_metadata.pop(stream_id, None)
        if self.current_stream_id == stream_id:
            self.current_stream_id = None

    async def _activate_next_stream(self) -> None:
        """Start playing the next queued TTS stream if idle."""
        if self.current_stream_id or not self.tts_stream_queue:
            return

        while self.tts_stream_queue:
            next_id = self.tts_stream_queue[0]
            buffers = self.tts_stream_buffers.setdefault(next_id, deque())
            self.current_stream_id = next_id

            await self._publish_tts_start(next_id)
            meta = self.tts_stream_metadata.setdefault(next_id, {})
            logging.info(
                "[TTS_STREAM] Activating stream %s (queued=%d)",
                next_id,
                len(self.tts_stream_queue),
            )

            first_buffered_chunk = True
            while buffers:
                chunk = buffers.popleft()
                await self._push_tts_chunk(chunk)
                if first_buffered_chunk:
                    logging.info(
                        f"[TTS_STREAM] First buffered chunk pushed ({len(chunk)} bytes) stream_id={next_id}"
                    )
                    first_buffered_chunk = False

            if meta.get("complete") and not self.tts_stream_buffers.get(next_id):
                await self._finalize_stream(next_id)
                # Continue loop to activate the next stream (if any)
                continue

            # Either stream still receiving chunks or waiting for completion.
            break

    def _resample_audio(self, frame: AudioFrame) -> np.ndarray:
        pcm = np.frombuffer(frame.data, dtype=np.int16)
        if frame.num_channels > 1:
            pcm = pcm.reshape(-1, frame.num_channels).mean(axis=1)
        if frame.sample_rate != INPUT_SAMPLE_RATE:
            resampled = resampy.resample(
                pcm.astype(np.float32), frame.sample_rate, INPUT_SAMPLE_RATE
            )
            return resampled.astype(np.int16)
        return pcm.astype(np.int16)

    @staticmethod
    def _resample_pcm16(audio_bytes: bytes, src_rate: int, dst_rate: int) -> bytes:
        if src_rate == dst_rate or not audio_bytes:
            return audio_bytes

        pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        resampled = resampy.resample(pcm, src_rate, dst_rate)
        return resampled.astype(np.int16).tobytes()

    @staticmethod
    def _compute_rms(chunk: bytes) -> float:
        if not chunk:
            return 0.0
        pcm = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
        if pcm.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(pcm**2)))

    async def _run_persistent_stt(
        self, queue: asyncio.Queue, participant_sid: str, participant_identity: str
    ):
        """
        Persistent STT worker that runs for the duration of the track.
        Continuously reads from queue, streams to Google, and updates shared state.
        """
        logging.info(
            f"[STT_WORKER] Starting persistent STT stream for {participant_identity}"
        )

        stop_event = asyncio.Event()
        restart_count = 0

        async def audio_generator():
            while True:
                chunk = await queue.get()
                if chunk is None:
                    stop_event.set()
                    return
                yield chunk

        while not stop_event.is_set():
            try:
                logging.info(
                    "[STT_WORKER] Opening Google stream (restart=%d) for %s",
                    restart_count,
                    participant_identity,
                )
                stream_iterator = self.stt_service.provider.stream_transcribe(
                    audio_generator()
                )

                async for result in stream_iterator:
                    text = (result.get("text") or "").strip()
                    is_final = bool(result.get("is_final"))

                    if text:
                        # Update shared state with latest transcript
                        if participant_sid not in self.stt_states:
                            self.stt_states[participant_sid] = {
                                "text": "",
                                "last_update": 0,
                            }

                        # #region agent log
                        prev = (self.stt_states[participant_sid].get("text") or "")[:80]
                        _debug_log(
                            "stt_state_update",
                            {
                                "is_final": is_final,
                                "text_len": len(text),
                                "text_preview": text[:80] if len(text) > 80 else text,
                                "prev_text_preview": prev,
                                "replaced_previous": bool(prev and prev != text[:80]),
                            },
                            "H1",
                            "livekit_bot:_run_persistent_stt",
                        )
                        # #endregion
                        self.stt_states[participant_sid]["text"] = text
                        self.stt_states[participant_sid][
                            "last_update"
                        ] = time.monotonic()

                        if is_final:
                            logging.info(f"[STT_STREAM] Google Final: '{text}'")
                        else:
                            logging.info(f"[STT_STREAM] Google Interim: '{text}'")

            except asyncio.CancelledError:
                if stop_event.is_set() or asyncio.current_task().cancelled():
                    raise
                logging.warning(
                    "[STT_WORKER] Stream cancelled by upstream; restarting for %s",
                    participant_identity,
                )
            except Exception as e:
                logging.error(
                    f"[STT_WORKER] Error in persistent stream: {e}", exc_info=True
                )

            if stop_event.is_set():
                break

            restart_count += 1
            await asyncio.sleep(min(2.0, 0.3 + restart_count * 0.2))

        logging.info(f"[STT_WORKER] Persistent stream ended for {participant_identity}")

    async def _process_audio_stream(
        self, track: Track, participant: Participant, track_sid: str | None = None
    ):
        """
        Process incoming audio stream with VAD and persistent STT streaming.
        """
        stt_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        stt_task = asyncio.create_task(
            self._run_persistent_stt(stt_queue, participant.sid, participant.identity)
        )

        # Initialize state for this participant
        self.stt_states[participant.sid] = {"text": "", "last_update": 0}

        wav_file = None
        wav_path = None
        wav_frames_written = 0
        utterance_index = 0
        max_frames = (
            int((self.save_audio_max_s * 1000) / FRAME_MS)
            if self.save_audio_max_s > 0
            else None
        )
        try:
            logging.info(
                f"[VAD_STREAM] Starting audio processing for {participant.identity} (track_sid={track_sid})"
            )
            vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
            state, voiced_run_ms, silence_run_ms = ASRState.IDLE, 0, 0
            audio_buffer = bytearray()

            # Rolling RMS accumulator for the current voiced run (barge-in energy gate)
            _barge_rms_sum = 0.0
            _barge_rms_count = 0
            _barge_rms_list: list[float] = []  # per-frame RMS for variance/peak gates

            utterance_start_time = 0.0
            utterance_total_frames = 0
            utterance_voiced_frames = 0
            utterance_rms_sum = 0.0
            utterance_rms_max = 0.0
            vad_end_time = 0.0
            frame_count = 0

            # TTS-window VAD stats: collected while tts_playing=True to measure how
            # much TTS leaks through the phone's AEC into the bot's mic stream.
            # Emitted as [TTS_VAD_STATS] logs once per second; purely observational —
            # barge-in logic is NOT modified by these values.
            _tts_vad_total = 0  # frames counted in the current 1-s window
            _tts_vad_voiced = 0  # voiced frames in the current window
            _tts_vad_cur_run_ms = 0  # current consecutive voiced run (ms)
            _tts_vad_max_run_ms = 0  # longest voiced run in the current window
            _tts_vad_rms_sum = 0.0  # RMS sum for mean calculation
            _tts_vad_rms_max = 0.0  # peak RMS in the current window
            _tts_vad_was_playing = False  # previous-frame tts_playing state
            _barge_was_tts_playing = (
                False  # tracks tts_playing transitions for barge-in reset
            )
            _tts_play_start_mono = 0.0  # monotonic timestamp when TTS playback began

            stream = AudioStream(track)
            first_frame_time = None

            async for ev in stream:
                if frame_count == 0:
                    first_frame_time = time.monotonic()
                    logging.info(
                        "[AUDIO_IN] First frame at t=%.3f: sample_rate=%s channels=%s bytes=%s",
                        first_frame_time,
                        ev.frame.sample_rate,
                        ev.frame.num_channels,
                        len(ev.frame.data),
                    )
                pcm16 = self._resample_audio(ev.frame)
                frame_count += 1
                if frame_count <= 5:
                    logging.info(
                        "[AUDIO_IN] Frame %d bytes=%d", frame_count, pcm16.nbytes
                    )
                audio_buffer.extend(pcm16.tobytes())

                # Always push to STT queue immediately (low latency)
                # But we need to chunk it for VAD
                # We can push to STT in larger chunks or same chunks?
                # Let's push to STT queue as soon as we have enough bytes for VAD,
                # or even immediately if we want.
                # But VAD works on 20ms frames (INPUT_FRAME_BYTES).

                while len(audio_buffer) >= INPUT_FRAME_BYTES:
                    vad_chunk = bytes(audio_buffer[:INPUT_FRAME_BYTES])
                    del audio_buffer[:INPUT_FRAME_BYTES]

                    # Push to persistent STT stream immediately
                    await stt_queue.put(vad_chunk)

                    if wav_file and (
                        max_frames is None or wav_frames_written < max_frames
                    ):
                        wav_file.writeframes(vad_chunk)
                        wav_frames_written += 1
                        if max_frames is not None and wav_frames_written == max_frames:
                            logging.info(
                                "[AUDIO_DUMP] Reached max duration (%.1fs). Closing file.",
                                self.save_audio_max_s,
                            )
                            wav_file.close()
                            wav_file = None

                    is_voiced = vad.is_speech(vad_chunk, INPUT_SAMPLE_RATE)

                    # ---- TTS-window VAD stats (observational, no barge-in logic) ----
                    if self.tts_playing:
                        _tts_vad_total += 1
                        if is_voiced:
                            _tts_vad_voiced += 1
                            _tts_vad_cur_run_ms += FRAME_MS
                            if _tts_vad_cur_run_ms > _tts_vad_max_run_ms:
                                _tts_vad_max_run_ms = _tts_vad_cur_run_ms
                        else:
                            _tts_vad_cur_run_ms = 0
                        _rms = self._compute_rms(vad_chunk)
                        _tts_vad_rms_sum += _rms
                        if _rms > _tts_vad_rms_max:
                            _tts_vad_rms_max = _rms
                        # Emit log and reset after every 1-second window (50 frames at 20ms)
                        if _tts_vad_total >= 50:
                            _voiced_ratio = _tts_vad_voiced / _tts_vad_total
                            _rms_mean = _tts_vad_rms_sum / _tts_vad_total
                            self._tts_window_rms_mean = _rms_mean
                            _room = self.room.name if self.room else "unknown_room"
                            logging.info(
                                "[TTS_VAD_STATS] room=%s voiced_ratio=%.2f "
                                "max_voiced_run_ms=%d rms_mean=%.0f rms_max=%.0f "
                                "barge_in_threshold_ms=%d",
                                _room,
                                _voiced_ratio,
                                _tts_vad_max_run_ms,
                                _rms_mean,
                                _tts_vad_rms_max,
                                BARGE_IN_SPEECH_MS,
                            )
                            # Reset window counters (per-window, not per-session)
                            _tts_vad_total = 0
                            _tts_vad_voiced = 0
                            _tts_vad_cur_run_ms = 0
                            _tts_vad_max_run_ms = 0
                            _tts_vad_rms_sum = 0.0
                            _tts_vad_rms_max = 0.0
                    elif _tts_vad_was_playing:
                        # TTS just stopped — reset all counters so the next TTS
                        # segment starts fresh.
                        _tts_vad_total = 0
                        _tts_vad_voiced = 0
                        _tts_vad_cur_run_ms = 0
                        _tts_vad_max_run_ms = 0
                        _tts_vad_rms_sum = 0.0
                        _tts_vad_rms_max = 0.0
                    _tts_vad_was_playing = self.tts_playing
                    # ---- end TTS-window VAD stats ----

                    # ---- Barge-in: reset on TTS start transition ----
                    if self.tts_playing and not _barge_was_tts_playing:
                        voiced_run_ms = 0
                        _barge_rms_sum = 0.0
                        _barge_rms_count = 0
                        _barge_rms_list = []
                        _tts_play_start_mono = time.monotonic()
                    _barge_was_tts_playing = self.tts_playing

                    if state == ASRState.IDLE:
                        if is_voiced:
                            _rms_frame = self._compute_rms(vad_chunk)
                            voiced_run_ms += FRAME_MS
                            _barge_rms_sum += _rms_frame
                            _barge_rms_count += 1
                            _barge_rms_list.append(_rms_frame)
                        else:
                            voiced_run_ms = 0
                            _barge_rms_sum = 0.0
                            _barge_rms_count = 0
                            _barge_rms_list = []

                        if self.tts_playing and voiced_run_ms >= BARGE_IN_SPEECH_MS:
                            # --- BARGE-IN PATH ---
                            # Child spoke over the bot with sustained speech.
                            # Use a higher threshold (BARGE_IN_SPEECH_MS) than normal
                            # start detection to reduce false positives from background noise.
                            _barge_avg_rms = _barge_rms_sum / max(1, _barge_rms_count)
                            _effective_min_rms = max(
                                BARGE_IN_MIN_RMS,
                                self._tts_window_rms_mean * 2.0,
                            )
                            if _barge_avg_rms < _effective_min_rms:
                                logging.info(
                                    "[BARGE_IN_SKIP] Ignoring low-energy voiced run: "
                                    "voiced_ms=%d avg_rms=%.1f (threshold=%.1f, tts_baseline=%.1f)",
                                    voiced_run_ms,
                                    _barge_avg_rms,
                                    _effective_min_rms,
                                    self._tts_window_rms_mean,
                                )
                                voiced_run_ms = 0
                                _barge_rms_sum = 0.0
                                _barge_rms_count = 0
                                _barge_rms_list = []
                                continue
                            # RMS variance gate: flat energy suggests background noise
                            if len(_barge_rms_list) >= 2:
                                _rms_std = float(np.std(_barge_rms_list))
                                _rms_cv = (
                                    _rms_std / _barge_avg_rms
                                    if _barge_avg_rms > 0
                                    else 0.0
                                )
                                if _rms_cv < BARGE_IN_MIN_RMS_CV:
                                    logging.info(
                                        "[BARGE_IN_SKIP] Low RMS variance (flat energy): "
                                        "voiced_ms=%d avg_rms=%.1f rms_cv=%.3f (min=%.2f)",
                                        voiced_run_ms,
                                        _barge_avg_rms,
                                        _rms_cv,
                                        BARGE_IN_MIN_RMS_CV,
                                    )
                                    voiced_run_ms = 0
                                    _barge_rms_sum = 0.0
                                    _barge_rms_count = 0
                                    _barge_rms_list = []
                                    continue
                            # Peak-to-mean ratio gate: near-field speech has sharp peaks
                            if _barge_rms_list:
                                _rms_max = max(_barge_rms_list)
                                _rms_peak_ratio = (
                                    _rms_max / _barge_avg_rms
                                    if _barge_avg_rms > 0
                                    else 0.0
                                )
                                if _rms_peak_ratio < BARGE_IN_MIN_PEAK_RATIO:
                                    logging.info(
                                        "[BARGE_IN_SKIP] Low peak-to-mean RMS ratio: "
                                        "voiced_ms=%d avg_rms=%.1f peak_ratio=%.2f (min=%.2f)",
                                        voiced_run_ms,
                                        _barge_avg_rms,
                                        _rms_peak_ratio,
                                        BARGE_IN_MIN_PEAK_RATIO,
                                    )
                                    voiced_run_ms = 0
                                    _barge_rms_sum = 0.0
                                    _barge_rms_count = 0
                                    _barge_rms_list = []
                                    continue
                            now = time.monotonic()
                            _cooldown_ref = (
                                self._tts_first_audio_push_mono
                                if self._tts_first_audio_push_mono > 0
                                else _tts_play_start_mono
                            )
                            _ms_since_tts_audio = (now - _cooldown_ref) * 1000
                            if _ms_since_tts_audio < BARGE_IN_COOLDOWN_MS:
                                logging.info(
                                    "[BARGE_IN_SKIP] Cooldown: %.0fms since %s "
                                    "(need %dms). voiced_ms=%d avg_rms=%.1f",
                                    _ms_since_tts_audio,
                                    (
                                        "first_audio_push"
                                        if self._tts_first_audio_push_mono > 0
                                        else "tts_start"
                                    ),
                                    BARGE_IN_COOLDOWN_MS,
                                    voiced_run_ms,
                                    _barge_avg_rms,
                                )
                                voiced_run_ms = 0
                                _barge_rms_sum = 0.0
                                _barge_rms_count = 0
                                _barge_rms_list = []
                                continue
                            gap_ok = (
                                now - self.last_barge_in_ts
                            ) >= MIN_GAP_BETWEEN_BARGE_IN_S
                            if gap_ok:
                                logging.info(
                                    "[BARGE_IN_ACCEPT] Triggering barge-in: "
                                    "voiced_ms=%d avg_rms=%.1f",
                                    voiced_run_ms,
                                    _barge_avg_rms,
                                )
                                await self._handle_barge_in(
                                    participant.identity, voiced_run_ms=voiced_run_ms
                                )
                                # Transition directly into IN_UTTERANCE so the interrupting
                                # speech is captured and transcribed normally.
                                utterance_start_time = time.monotonic()
                                logging.info(
                                    f"[VAD_START] Barge-in utterance start for {participant.identity}"
                                )
                                state = ASRState.IN_UTTERANCE
                                self.stt_states[participant.sid]["text"] = ""
                                utterance_total_frames = 0
                                utterance_voiced_frames = 0
                                utterance_rms_sum = 0.0
                                utterance_rms_max = 0.0
                                silence_run_ms = 0
                                _barge_rms_sum = 0.0
                                _barge_rms_count = 0
                                _barge_rms_list = []
                                if self.save_audio_enabled:
                                    self.save_audio_dir.mkdir(
                                        parents=True, exist_ok=True
                                    )
                                    ts = time.strftime("%Y%m%d_%H%M%S")
                                    room_name_str = (
                                        self.room.name if self.room else "unknown_room"
                                    )
                                    utterance_index += 1
                                    filename = (
                                        f"{room_name_str}_{participant.identity}_"
                                        f"{track_sid or 'track'}_utt{utterance_index}_{ts}.wav"
                                    )
                                    wav_path = self.save_audio_dir / filename
                                    wav_file = wave.open(str(wav_path), "wb")
                                    wav_file.setnchannels(1)
                                    wav_file.setsampwidth(2)
                                    wav_file.setframerate(INPUT_SAMPLE_RATE)
                                    wav_frames_written = 0
                                    logging.info(
                                        "[AUDIO_DUMP] Recording barge-in utterance to %s",
                                        wav_path,
                                    )
                            else:
                                # Too soon after last barge-in — reset counter to avoid
                                # the child's barge-in response immediately re-triggering.
                                voiced_run_ms = 0
                                _barge_rms_sum = 0.0
                                _barge_rms_count = 0
                                _barge_rms_list = []

                        elif not self.tts_playing and voiced_run_ms >= START_SPEECH_MS:
                            # --- NORMAL START PATH ---
                            # Apply grace period suppression only here (post-TTS echo tail),
                            # NOT during active TTS where barge-in detection handles it.
                            now = time.monotonic()
                            tts_grace_period = max(
                                0.3, min(2.0, self.last_chunk_duration_s + 0.05)
                            )
                            is_in_grace = (
                                self.tts_end_time > 0
                                and (now - self.tts_end_time) < tts_grace_period
                            )

                            if not is_in_grace:
                                utterance_start_time = time.monotonic()
                                logging.info(
                                    f"[VAD_START] Speech start for {participant.identity}"
                                )
                                # #region agent log
                                cleared_preview = (
                                    self.stt_states[participant.sid].get("text") or ""
                                )[:80]
                                _debug_log(
                                    "vad_start",
                                    {
                                        "first_frame_time": first_frame_time,
                                        "utterance_start_time": utterance_start_time,
                                        "delay_since_first_frame_s": (
                                            utterance_start_time - first_frame_time
                                            if first_frame_time
                                            else None
                                        ),
                                        "frame_count_at_start": frame_count,
                                        "cleared_text_preview": cleared_preview,
                                    },
                                    "H2",
                                    "livekit_bot:_process_audio_stream",
                                )
                                if cleared_preview:
                                    _debug_log(
                                        "vad_start_clear",
                                        {"cleared_text_preview": cleared_preview},
                                        "H4",
                                        "livekit_bot:_process_audio_stream",
                                    )
                                # #endregion
                                state = ASRState.IN_UTTERANCE
                                # Clear previous transcript for this utterance
                                self.stt_states[participant.sid]["text"] = ""
                                utterance_total_frames = 0
                                utterance_voiced_frames = 0
                                utterance_rms_sum = 0.0
                                utterance_rms_max = 0.0
                                if self.save_audio_enabled:
                                    self.save_audio_dir.mkdir(
                                        parents=True, exist_ok=True
                                    )
                                    ts = time.strftime("%Y%m%d_%H%M%S")
                                    room_name = (
                                        self.room.name if self.room else "unknown_room"
                                    )
                                    utterance_index += 1
                                    filename = (
                                        f"{room_name}_{participant.identity}_"
                                        f"{track_sid or 'track'}_utt{utterance_index}_{ts}.wav"
                                    )
                                    wav_path = self.save_audio_dir / filename
                                    wav_file = wave.open(str(wav_path), "wb")
                                    wav_file.setnchannels(1)
                                    wav_file.setsampwidth(2)
                                    wav_file.setframerate(INPUT_SAMPLE_RATE)
                                    wav_frames_written = 0
                                    logging.info(
                                        "[AUDIO_DUMP] Recording utterance audio to %s",
                                        wav_path,
                                    )

                            silence_run_ms = 0

                    elif state == ASRState.IN_UTTERANCE:
                        silence_run_ms = (
                            silence_run_ms + FRAME_MS if not is_voiced else 0
                        )
                        if silence_run_ms >= END_SPEECH_MS:
                            vad_end_time = time.monotonic()
                            logging.info(
                                f"[VAD_END] Speech end for {participant.identity} at t={vad_end_time:.3f}, entering post-roll"
                            )
                            state = ASRState.POST_ROLL
                            silence_run_ms = 0  # reset so POST_ROLL_MS actually elapses

                    elif state == ASRState.POST_ROLL:
                        silence_run_ms += FRAME_MS
                        if silence_run_ms >= POST_ROLL_MS:
                            # Finalize utterance
                            duration_ms = (
                                time.monotonic() - utterance_start_time
                            ) * 1000
                            logging.info(
                                f"[VAD_COMPLETE] Utterance complete for {participant.identity} (duration={duration_ms:.0f}ms)"
                            )

                            voiced_ratio = utterance_voiced_frames / max(
                                1, utterance_total_frames
                            )
                            avg_rms = utterance_rms_sum / max(1, utterance_total_frames)
                            if self.enable_utterance_gating and (
                                duration_ms < self.min_utterance_ms
                                or utterance_voiced_frames < self.min_voiced_frames
                                or voiced_ratio < self.min_voiced_ratio
                                or avg_rms < self.min_utterance_rms
                            ):
                                logging.info(
                                    "[VAD_DROP] Dropping low-quality utterance: "
                                    "duration=%.0fms, frames=%d, voiced=%d, voiced_ratio=%.2f, "
                                    "avg_rms=%.1f, max_rms=%.1f",
                                    duration_ms,
                                    utterance_total_frames,
                                    utterance_voiced_frames,
                                    voiced_ratio,
                                    avg_rms,
                                    utterance_rms_max,
                                )
                                if wav_file:
                                    wav_file.close()
                                    wav_file = None
                                if wav_path and os.path.exists(wav_path):
                                    os.remove(wav_path)
                                    logging.info(
                                        "[AUDIO_DUMP] Dropped utterance file %s",
                                        wav_path,
                                    )
                                state = ASRState.IDLE
                                voiced_run_ms = 0
                                silence_run_ms = 0
                                continue

                            # Grab latest text from persistent STT (full text via concatenation in google_stt)
                            transcription = (
                                self.stt_states[participant.sid].get("text") or ""
                            )
                            if not transcription and self.stt_wait_after_vad_ms > 0:
                                wait_deadline = time.monotonic() + (
                                    self.stt_wait_after_vad_ms / 1000.0
                                )
                                while time.monotonic() < wait_deadline:
                                    await asyncio.sleep(0.05)
                                    transcription = (
                                        self.stt_states[participant.sid].get("text")
                                        or ""
                                    )
                                    if transcription:
                                        break
                            # #region agent log
                            _debug_log(
                                "vad_complete_grab",
                                {
                                    "transcription": (
                                        transcription[:120] if transcription else ""
                                    ),
                                    "transcription_len": len(transcription or ""),
                                    "duration_ms": duration_ms,
                                    "utterance_total_frames": utterance_total_frames,
                                    "expected_ms_from_frames": utterance_total_frames
                                    * FRAME_MS,
                                },
                                "H1",
                                "livekit_bot:_process_audio_stream",
                            )
                            # #endregion

                            # Publish if valid
                            if transcription:
                                turn_id = uuid.uuid4().hex[:8]
                                publish_time = time.monotonic()
                                publish_time_wallclock = time.time()
                                total_latency = publish_time - utterance_start_time
                                vad_to_publish = (
                                    publish_time - vad_end_time
                                    if vad_end_time > 0
                                    else 0
                                )
                                # ts_vad_end: wallclock timestamp of VAD boundary
                                ts_vad_end = publish_time_wallclock - vad_to_publish
                                task = {
                                    "turn_id": turn_id,
                                    "room_name": self.room.name,
                                    "participant_identity": participant.identity,
                                    "transcription": transcription,
                                    "duration_ms": duration_ms,
                                    "stt_latency_s": total_latency,
                                    "publish_timestamp": publish_time_wallclock,
                                    "vad_end_to_publish_s": vad_to_publish,
                                    "ts_vad_end": ts_vad_end,
                                }
                                await self.redis_client.publish(
                                    "jubu_tasks", json.dumps(task)
                                )
                                logging.info(
                                    f"[STT_PUBLISHED] '{transcription}' (latency={total_latency:.2f}s, "
                                    f"VAD_END→publish={vad_to_publish:.3f}s)"
                                )

                                # Clear shared state so we don't republish same text
                                self.stt_states[participant.sid]["text"] = ""
                            else:
                                logging.warning(
                                    f"[STT_SKIP] No transcription available at VAD boundary"
                                )

                            if wav_file:
                                wav_file.close()
                                wav_file = None
                            wav_path = None
                            state = ASRState.IDLE
                            voiced_run_ms = 0
                            silence_run_ms = 0
                            continue

                    if state in (ASRState.IN_UTTERANCE, ASRState.POST_ROLL):
                        utterance_total_frames += 1
                        if is_voiced:
                            utterance_voiced_frames += 1
                        if self.enable_utterance_gating:
                            rms = self._compute_rms(vad_chunk)
                            utterance_rms_sum += rms
                            if rms > utterance_rms_max:
                                utterance_rms_max = rms

        except Exception as e:
            logging.error(
                f"Error processing audio stream for {participant.identity}: {e}",
                exc_info=True,
            )
        finally:
            # Clean up
            await stt_queue.put(None)
            await stt_task
            if wav_file:
                wav_file.close()
            logging.info(f"Audio stream processing ended for {participant.identity}")

    async def _redis_subscriber(self):
        pubsub = self.redis_client.pubsub()
        # Only subscribe to streaming TTS channel (batch TTS deprecated)
        await pubsub.subscribe("jubu_tts_stream")
        logging.info("Subscribed to Redis streaming TTS channel.")

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])

                    # REMOVED: Batch TTS handling (deprecated - only using streaming now)
                    # If you need batch TTS again, subscribe to "jubu_results" channel
                    # and add back the _push_tts_audio method

                    # Handle streaming TTS
                    if message["channel"] == b"jubu_tts_stream":
                        if self.room and data.get("room_name") == self.room.name:
                            await self._handle_tts_stream_event(data)

                except Exception as e:
                    logging.error(f"Error processing Redis message: {e}", exc_info=True)

    async def _handle_tts_stream_event(self, data: dict):
        """Handle streaming TTS events from thinker."""
        event = data.get("event")

        stream_id = data.get("stream_id") or "__legacy__"

        # After a barge-in, _handle_barge_in() clears tts_stream_queue, tts_stream_buffers,
        # and tts_stream_metadata, and sets current_stream_id=None.  Any chunk/complete
        # events that arrive afterwards for the interrupted stream_id should be silently
        # dropped so they can't re-activate playback.
        if (
            stream_id != "__legacy__"
            and event in ("chunk", "stream_complete")
            and stream_id not in self.tts_stream_queue
            and stream_id != self.current_stream_id
            and stream_id not in self.tts_stream_buffers
        ):
            logging.debug(
                "[TTS_STREAM] Dropping stale %s for interrupted stream %s",
                event,
                stream_id[:20],
            )
            return

        if event == "stream_start":
            text_preview = data.get("text", "")[:50]
            logging.info(
                f"[TTS_STREAM] Starting: '{text_preview}...' stream_id={stream_id}"
            )

            if stream_id != "__legacy__":
                if stream_id not in self.tts_stream_queue:
                    self.tts_stream_queue.append(stream_id)
                self.tts_stream_buffers.setdefault(stream_id, deque())
                self.tts_stream_metadata.setdefault(
                    stream_id,
                    {
                        "total_bytes": 0,
                        "chunks": 0,
                        "text": data.get("text", ""),
                        "turn_id": data.get("turn_id", stream_id[:8]),
                        "conversation_id": data.get("conversation_id"),
                        "anchor_ts": data.get("anchor_ts"),
                        "anchor_name": data.get("anchor_name"),
                    },
                )
                await self._activate_next_stream()
            else:
                # Legacy path: play immediately
                await self._publish_tts_start(stream_id)

        elif event == "chunk":
            receive_time = time.monotonic()
            receive_wallclock = time.time()
            audio_b64 = data.get("audio_b64", "")
            if not audio_b64:
                return

            audio_chunk = base64.b64decode(audio_b64)

            meta = self.tts_stream_metadata.setdefault(
                stream_id, {"total_bytes": 0, "chunks": 0}
            )
            meta["total_bytes"] = meta.get("total_bytes", 0) + len(audio_chunk)
            chunk_num = meta.get("chunks", 0) + 1
            meta["chunks"] = chunk_num

            # Track first-chunk receive timestamp for latency logging
            if chunk_num == 1:
                meta["ts_first_chunk_recv"] = receive_wallclock

            logging.info(
                f"[TTS_RECV] Chunk #{chunk_num} received from Redis: {len(audio_chunk)} bytes, "
                f"stream_id={stream_id[:20]}..."
            )

            if stream_id == "__legacy__":
                await self._push_tts_chunk(audio_chunk)
                return

            buffers = self.tts_stream_buffers.setdefault(stream_id, deque())
            if stream_id == self.current_stream_id:
                await self._push_tts_chunk(audio_chunk)
                if chunk_num == 1:
                    logging.info(
                        f"[TTS_STREAM] First chunk pushed ({len(audio_chunk)} bytes) stream_id={stream_id}"
                    )
            else:
                buffers.append(audio_chunk)
                logging.info(
                    f"[TTS_QUEUE] Chunk #{chunk_num} queued (not current stream)"
                )

            await self._activate_next_stream()

        elif event == "stream_complete":
            total_bytes = data.get("total_bytes", 0)
            chunks = data.get("chunks", 0)

            if stream_id == "__legacy__":
                logging.info(
                    f"[TTS_STREAM] Complete: {chunks} chunks, {total_bytes} bytes (legacy)"
                )
                # Flush leftover so it doesn't bleed into the next stream (legacy has no _finalize_stream).
                if self._tts_leftover and self.tts_source is not None:
                    pad_len = OUTPUT_FRAME_BYTES - len(self._tts_leftover)
                    padded = self._tts_leftover + b"\x00" * pad_len
                    frame = AudioFrame(
                        data=padded,
                        sample_rate=OUTPUT_SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=OUTPUT_FRAME_BYTES // 2,
                    )
                    await self.tts_source.capture_frame(frame)
                    self._tts_leftover = b""
                # Mark TTS as ended (for echo suppression)
                self.tts_playing = False
                self.tts_end_time = time.monotonic()
                # Grace period = last chunk duration + 50ms buffer
                grace_period = self.last_chunk_duration_s + 0.05
                logging.info(
                    f"[TTS_SUPPRESS] Legacy TTS playback ended, will suppress STT for {grace_period:.3f}s grace period "
                    f"(last_chunk={self.last_chunk_duration_s:.3f}s)"
                )
                await self.redis_client.publish(
                    "jubu_tts_events",
                    json.dumps(
                        {
                            "event": "tts_complete",
                            "room_name": self.room.name if self.room else "",
                            "total_bytes": total_bytes,
                            "event_ts": time.time(),
                        }
                    ),
                )
                return

            meta = self.tts_stream_metadata.setdefault(stream_id, {})
            meta["total_bytes"] = total_bytes
            meta["chunks"] = chunks
            meta["complete"] = True

            buffers = self.tts_stream_buffers.setdefault(stream_id, deque())
            if stream_id == self.current_stream_id and not buffers:
                await self._finalize_stream(stream_id)
                await self._activate_next_stream()

        elif event == "error":
            logging.error(
                f"[TTS_STREAM] Error: {data.get('error')} stream_id={stream_id}"
            )
            if stream_id != "__legacy__":
                # If this was the active stream, reset state and end TTS suppression
                was_current = self.current_stream_id == stream_id
                if was_current:
                    self.current_stream_id = None
                    self.tts_playing = False
                    self.tts_end_time = time.monotonic()
                    self._tts_leftover = (
                        b""  # discard partial frame from abandoned stream
                    )
                    logging.info(
                        f"[TTS_SUPPRESS] Error occurred, ending TTS suppression"
                    )

                # Clean up any pending state for the errored stream
                try:
                    self.tts_stream_queue.remove(stream_id)
                except ValueError:
                    pass
                self.tts_stream_buffers.pop(stream_id, None)
                self.tts_stream_metadata.pop(stream_id, None)

                # Try to activate next stream if we were playing the errored one
                if was_current:
                    await self._activate_next_stream()

    async def _push_tts_chunk(self, audio_chunk: bytes):
        """Push a single TTS audio chunk (for streaming TTS).

        ElevenLabs returns raw PCM16 at 16kHz, which now matches OUTPUT_SAMPLE_RATE,
        so no resampling is needed.  Leftover bytes from the previous call are
        prepended before slicing into OUTPUT_FRAME_BYTES frames so that chunk
        boundaries never introduce zero-padding artifacts mid-stream.  Only a
        complete silence-pad at the very end of a stream (in _finalize_stream) is
        acceptable.
        """
        assert self.tts_source is not None

        # Barge-in guard: if playback was stopped before this call, discard the chunk
        # and clear leftover so the next stream doesn't inherit stale bytes.
        if not self.tts_playing or self.current_stream_id is None:
            self._tts_leftover = b""
            return

        total_start = time.monotonic()
        push_wallclock = time.time()

        # Prepend any partial frame carried over from the previous chunk call.
        data = self._tts_leftover + audio_chunk
        self._tts_leftover = b""

        frame_count = 0
        bytes_pushed = 0
        i = 0
        while i + OUTPUT_FRAME_BYTES <= len(data):
            # Barge-in guard: re-check each frame so playback stops as quickly as
            # possible after _handle_barge_in() clears state, without finishing
            # the entire in-flight chunk.
            if not self.tts_playing or self.current_stream_id is None:
                self._tts_leftover = b""
                break
            frame_data = data[i : i + OUTPUT_FRAME_BYTES]
            frame = AudioFrame(
                data=frame_data,
                sample_rate=OUTPUT_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=OUTPUT_FRAME_BYTES // 2,
            )
            await self.tts_source.capture_frame(frame)
            frame_count += 1
            bytes_pushed += OUTPUT_FRAME_BYTES
            i += OUTPUT_FRAME_BYTES

        # Save any trailing bytes that didn't fill a complete frame (only when
        # playback is still active; cleared above if barge-in stopped us mid-loop).
        if i < len(data) and self.tts_playing and self.current_stream_id is not None:
            self._tts_leftover = data[i:]

        total_duration_s = bytes_pushed / (OUTPUT_SAMPLE_RATE * 2)
        self.last_chunk_duration_s = total_duration_s

        if self.current_stream_id:
            meta = self.tts_stream_metadata.get(self.current_stream_id)
            if meta is not None:
                is_first_push = "ts_first_chunk_pushed" not in meta
                if is_first_push:
                    meta["ts_first_chunk_pushed"] = push_wallclock
                    self._tts_first_audio_push_mono = total_start
                    await self.redis_client.publish(
                        "jubu_tts_events",
                        json.dumps(
                            {
                                "event": "tts_first_audio",
                                "room_name": self.room.name if self.room else "",
                                "stream_id": self.current_stream_id,
                                "turn_id": meta.get("turn_id"),
                                "event_ts": push_wallclock,
                            }
                        ),
                    )
                meta["ts_last_chunk_pushed"] = push_wallclock

        total_elapsed = time.monotonic() - total_start
        logging.info(
            f"[TTS_PUSH] Chunk pushed: audio_duration={total_duration_s:.3f}s, "
            f"push={total_elapsed:.3f}s, frames={frame_count}, "
            f"leftover={len(self._tts_leftover)}B"
        )

    # REMOVED: _push_tts_audio() - Batch TTS deprecated, only using streaming TTS now
    # If you need batch TTS again, add it back and subscribe to "jubu_results" in _redis_subscriber

    async def run(self, room_name: str, identity: str):
        # Initialize STT service first (ensures it attaches to this event loop)
        await self._initialize_stt()

        self.room_name = room_name
        self.identity = identity

        token = (
            AccessToken(self.api_key, self.api_secret)
            .with_identity(self.identity)
            .with_grants(VideoGrants(room_join=True, room=self.room_name))
            .to_jwt()
        )

        # Create Room and register event handlers using decorator syntax
        self.room = Room()

        @self.room.on("connection_state_changed")
        def _on_connection_state_changed(state):
            logging.info(f"[EVENT] connection_state_changed -> {state}")

        @self.room.on("connected")
        def _on_connected():
            logging.info(f"[EVENT] connected to room: {self.room.name}")
            logging.info(
                f"[EVENT] Existing participants: {[p.identity for p in self.room.remote_participants.values()]}"
            )

        @self.room.on("participant_connected")
        def _on_participant_connected(p: Participant):
            logging.info(f"[EVENT] participant_connected: {p.identity}")

        @self.room.on("participant_disconnected")
        def _on_participant_disconnected(p: Participant):
            logging.info(f"[EVENT] participant_disconnected: {p.identity}")

            # Notify thinker so end_conversation (and capability evaluation) runs.
            # Fires for any remote participant leaving (typical: one child per room).
            async def _notify_participant_left():
                try:
                    raw = await self.redis_client.get(
                        f"room:{self.room.name}:conversation_id"
                    )
                    if raw is None:
                        return
                    conv_id = raw.decode() if isinstance(raw, bytes) else raw
                    await self.redis_client.publish(
                        "conversation_events",
                        json.dumps(
                            {
                                "event": "participant_disconnected",
                                "conversation_id": conv_id,
                                "room_name": self.room.name,
                            }
                        ),
                    )
                    logging.info(
                        "Published participant_disconnected for conversation %s",
                        conv_id,
                    )
                except Exception as e:
                    logging.error("Failed to publish participant_disconnected: %s", e)

            try:
                asyncio.get_running_loop().create_task(_notify_participant_left())
            except RuntimeError:
                pass

        @self.room.on("track_published")
        def _on_track_published(pub: TrackPublication, p: Participant):
            logging.info(
                f"[EVENT] track_published: from={p.identity} kind={pub.kind} name={pub.name}"
            )
            if not self._should_process_publication(pub, p):
                return
            if pub.sid in self.active_track_sids:
                logging.debug("Track %s already active, ignoring publish", pub.sid)
                return
            logging.info(f"Track published by {p.identity}, subscribing...")
            pub.set_subscribed(True)  # This is synchronous, not async

        @self.room.on("track_subscribed")
        def _on_track_subscribed(track: Track, pub: TrackPublication, p: Participant):
            logging.info(
                f"[EVENT] track_subscribed: from={p.identity} kind={track.kind} name={pub.name}"
            )
            if not self._should_process_publication(pub, p):
                return

            track_sid = getattr(pub, "sid", None)
            if track_sid and track_sid in self.active_track_sids:
                logging.info(
                    "Already processing track %s from %s, ignoring duplicate subscription",
                    track_sid,
                    p.identity,
                )
                return

            if (
                p.sid in self.processing_tasks
                and not self.processing_tasks[p.sid].done()
            ):
                logging.warning(
                    f"Already processing a stream for {p.identity}. Ignoring new track."
                )
                return

            logging.info(
                f"Starting audio processing for {p.identity} (track_sid={track_sid})"
            )
            task = asyncio.create_task(self._process_audio_stream(track, p, track_sid))
            self.processing_tasks[p.sid] = task
            if track_sid:
                self.active_track_sids.add(track_sid)

        logging.info("Connecting to LiveKit room...")
        await self.room.connect(self.livekit_url, token)
        logging.info("LiveKit connection successful.")

        # Debug: Log current room state
        logging.info(f"Room name: {self.room.name}")
        logging.info(f"Local participant: {self.room.local_participant.identity}")
        logging.info(
            f"Remote participants: {list(self.room.remote_participants.keys())}"
        )

        # Manually subscribe to existing participants' tracks
        for participant_id, participant in self.room.remote_participants.items():
            logging.info(f"Found existing participant: {participant.identity}")
            for track_sid, publication in participant.track_publications.items():
                logging.info(
                    f"  Track: {publication.name} kind={publication.kind} subscribed={publication.subscribed}"
                )
                if (
                    publication.kind == TrackKind.KIND_AUDIO
                    and not publication.subscribed
                ):
                    logging.info(f"  Subscribing to track {track_sid}")
                    publication.set_subscribed(True)

        # Give the event loop a moment to process any pending events
        await asyncio.sleep(0.5)

        print(f"[INFO] Creating AudioSource...", flush=True)
        self.tts_source = AudioSource(OUTPUT_SAMPLE_RATE, 1)
        print(f"[INFO] AudioSource created.", flush=True)

        print(f"[INFO] Creating LocalAudioTrack...", flush=True)
        track = LocalAudioTrack.create_audio_track("bot-tts", self.tts_source)
        print(f"[INFO] LocalAudioTrack created.", flush=True)

        try:
            print(f"[INFO] Publishing TTS audio track...", flush=True)
            # Use a timeout to avoid hanging forever
            publication = await asyncio.wait_for(
                self.room.local_participant.publish_track(track), timeout=5.0
            )
            logging.info(f"Published TTS audio track: {publication}")
        except asyncio.TimeoutError:
            logging.warning(
                "TIMEOUT publishing track after 5s. Track may still publish in background."
            )
            print(f"[WARN] Publish timed out, continuing anyway...", flush=True)
        except TypeError as e:
            # Fallback for SDK versions where publish_track is not async
            logging.warning(f"TypeError during publish, trying sync: {e}")
            self.room.local_participant.publish_track(track)
            logging.info("Published TTS audio track (sync).")
        except Exception as e:
            logging.error(f"Failed to publish TTS track: {e}", exc_info=True)
            print(f"[ERROR] Failed to publish TTS track: {e}", flush=True)
            raise

        redis_task = asyncio.create_task(self._redis_subscriber())
        print(f"[INFO] [BOT_READY]", flush=True)
        logging.info("[BOT_READY]")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()
        redis_task.cancel()
        await self.room.disconnect()
        await self.redis_client.aclose()


if __name__ == "__main__":
    LIVEKIT_URL = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880")
    API_KEY = os.getenv("LIVEKIT_API_KEY", "devkey")
    API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret")
    ROOM_NAME = os.getenv("LIVEKIT_ROOM", "test")
    IDENTITY = os.getenv("LIVEKIT_IDENTITY", "buju-ai")
    STT_PROVIDER = os.getenv("STT_PROVIDER", "google")

    try:
        logging.info(
            f"🚀 Starting bot for room {ROOM_NAME} with STT provider: {STT_PROVIDER}"
        )
        bot = Bot(LIVEKIT_URL, API_KEY, API_SECRET, stt_provider=STT_PROVIDER)
        asyncio.run(bot.run(ROOM_NAME, IDENTITY))
    except Exception as e:
        logging.error(f"❌ Bot failed to start: {e}", exc_info=True)
        import sys

        sys.exit(1)
