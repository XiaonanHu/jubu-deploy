import asyncio
import base64
import collections
import contextlib
import io
import json
import logging
import os
import re
import threading
import time
import uuid
import wave
from pathlib import Path

import redis.asyncio as redis
from dotenv import load_dotenv
from pydub import AudioSegment

from api_server.jubu_adapter import JubuAdapter
from jubu_chat.chat.common.exceptions import SafetyEvaluationError
from jubu_chat.chat.utils.voice_sanitizer import sanitize_for_tts

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

LATENCY_LOG_DIR = Path(os.getenv("LATENCY_LOG_DIR", "latency/runs"))
CONVERSATION_LATENCY_LOG_DIR = Path(
    os.getenv("CONVERSATION_LATENCY_LOG_DIR", "logs/latency/conversation_logs")
)
ENABLE_CONVERSATION_LATENCY_JSON_LOGGING = (
    os.getenv("ENABLE_CONVERSATION_LATENCY_JSON_LOGGING", "1") == "1"
)


def _append_jsonl(filepath: Path, record: dict) -> None:
    """Append a JSON record as a new line to a JSONL file."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        logging.error("[JSONL] Failed to write %s: %s", filepath, exc)


RATE = 16000


def _select_user_perceived_ttfa_anchor(
    timing_ctx: dict,
) -> tuple[str | None, float | None]:
    """
    Pick the earliest reliable wallclock timestamp that approximates
    "user finished speaking" for backend-only TTFA estimation.

    Priority:
      1) ts_vad_end (best signal for end-of-user-speech)
      2) ts_stt_published (turn committed/published by bot process)
      3) ts_thinker_recv (task received by thinker)
    """
    candidates = (
        ("ts_vad_end", timing_ctx.get("ts_vad_end")),
        ("ts_stt_published", timing_ctx.get("ts_stt_published")),
        ("ts_thinker_recv", timing_ctx.get("ts_thinker_recv")),
    )
    for name, value in candidates:
        if isinstance(value, (int, float)):
            return name, float(value)
    return None, None


class Thinker:
    def __init__(self):
        self.redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost"))
        self.adapter = JubuAdapter()
        # The adapter now manages its own conversation states internally
        self._warmup_in_progress: set[str] = set()
        self._init_locks: collections.defaultdict[str, asyncio.Lock] = (
            collections.defaultdict(asyncio.Lock)
        )
        # Barge-in cancellation: per-room asyncio.Event set when jubu_interrupt arrives.
        # Checked in _stream_tts() and _live_token_gen() to stop generation early.
        self._cancel_events: collections.defaultdict[str, asyncio.Event] = (
            collections.defaultdict(asyncio.Event)
        )
        # Tracks the currently-active TTS stream_id per room so that _listen_interrupts()
        # can reject delayed/duplicate interrupt messages for already-finished streams.
        self._active_stream_id_by_room: dict[str, str] = {}

    def _initialize_conversation_if_needed(
        self, room_name: str, streaming_tts: bool = False
    ):
        """Initialize conversation if not already active.

        Note: In production, conversations should be initialized via the API first.
        This is a fallback for testing without the API.
        """
        if not self.adapter.is_conversation_active(room_name):
            logging.warning(
                f"Conversation not initialized for room {room_name}. Auto-initializing with streaming_tts={streaming_tts}"
            )
            logging.warning(
                "In production, initialize conversations via the API endpoint first!"
            )
            self.adapter.initialize_conversation(
                conversation_id=room_name,
                interaction_type="chitchat",
                stt_provider="google",
                tts_provider="elevenlabs",
                streaming_tts=streaming_tts,
            )

    async def ensure_initialized(self, conv_key: str, streaming_tts: bool):
        lock = self._init_locks[conv_key]
        async with lock:
            self._initialize_conversation_if_needed(conv_key, streaming_tts)

    async def _warm_conversation(self, conversation_id: str):
        try:
            config = await self.redis_client.hgetall(f"conversation:{conversation_id}")
            streaming_tts = False
            if config and b"streaming_tts" in config:
                streaming_tts = config[b"streaming_tts"].decode().lower() == "true"
            await self.ensure_initialized(conversation_id, streaming_tts)
            logging.info(
                "[WARMUP] Pre-initialized conversation %s (streaming_tts=%s)",
                conversation_id,
                streaming_tts,
            )
        except Exception as exc:
            logging.error(
                "[WARMUP] Failed to pre-initialize conversation %s: %s",
                conversation_id,
                exc,
                exc_info=True,
            )
        finally:
            self._warmup_in_progress.discard(conversation_id)

    async def _listen_conversation_events(self):
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("conversation_events")
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception as exc:
                logging.warning("Failed to decode conversation event: %s", exc)
                continue

            event = data.get("event")
            conversation_id = data.get("conversation_id")
            room_name = data.get("room_name")

            if not conversation_id:
                continue

            if event == "conversation_initialized":
                if (
                    conversation_id in self._warmup_in_progress
                    or self.adapter.is_conversation_active(conversation_id)
                ):
                    continue
                self._warmup_in_progress.add(conversation_id)
                asyncio.create_task(self._warm_conversation(conversation_id))
            elif event == "conversation_ended":
                self._warmup_in_progress.discard(conversation_id)
                if self.adapter.is_conversation_active(conversation_id):
                    self.adapter.cleanup_conversation_resources(conversation_id)
            elif event == "participant_disconnected":
                # Frontend/user left the room; run end_conversation (and capability evaluation)
                self._warmup_in_progress.discard(conversation_id)
                if self.adapter.is_conversation_active(conversation_id):
                    self.adapter.cleanup_conversation_resources(conversation_id)
                    logging.info(
                        "Cleaned up conversation %s after participant_disconnected",
                        conversation_id,
                    )
                if room_name:
                    await self.redis_client.delete(f"room:{room_name}:conversation_id")
                    await self.redis_client.publish(
                        "conversation_events",
                        json.dumps(
                            {
                                "event": "conversation_ended",
                                "conversation_id": conversation_id,
                                "room_name": room_name,
                            }
                        ),
                    )
                    logging.info(
                        "Published conversation_ended for room %s (participant left)",
                        room_name,
                    )
                await self.redis_client.delete(f"conversation:{conversation_id}")

    async def _listen_interrupts(self):
        """Subscribe to jubu_interrupt and set per-room cancel events."""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("jubu_interrupt")
        logging.info("[INTERRUPT] Subscribed to jubu_interrupt channel")
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception as exc:
                logging.warning("[INTERRUPT] Failed to decode interrupt event: %s", exc)
                continue
            room_name = data.get("room_name")
            stream_id = data.get("stream_id")
            if room_name:
                active_stream = self._active_stream_id_by_room.get(room_name)
                # Only cancel if the interrupt targets the stream currently being
                # generated.  If stream_id is absent (legacy message) we still
                # cancel for backward compatibility.
                if not stream_id or stream_id == active_stream:
                    self._cancel_events[room_name].set()
                    logging.info(
                        "[INTERRUPT] Cancel flag set for room=%s stream_id=%s",
                        room_name,
                        stream_id,
                    )
                else:
                    logging.info(
                        "[INTERRUPT] Ignoring stale interrupt for room=%s "
                        "stream_id=%s (active=%s)",
                        room_name,
                        stream_id,
                        active_stream,
                    )

    async def process_task(self, task_data: dict):
        task_start_time = time.monotonic()
        task_start_wallclock = time.time()
        room_name = task_data["room_name"]

        # Clear any previous barge-in cancel flag for this room so the new turn
        # isn't immediately cancelled if a stale interrupt event is lingering.
        self._cancel_events[room_name].clear()

        # Receive transcription text directly (not audio bytes)
        transcription = task_data.get("transcription", "")
        duration_ms = task_data.get("duration_ms", 0)
        stt_latency_s = task_data.get("stt_latency_s", 0)
        publish_timestamp = task_data.get("publish_timestamp")
        turn_id = task_data.get("turn_id") or uuid.uuid4().hex[:8]
        ts_vad_end = task_data.get("ts_vad_end")

        redis_latency_ms = 0
        if publish_timestamp:
            redis_latency_ms = (task_start_wallclock - publish_timestamp) * 1000

        logging.info(
            f"[THINKER_RECV] ← Received transcription for room {room_name} at t={task_start_time:.3f}: "
            f"'{transcription}' (audio_duration={duration_ms:.0f}ms, stt_latency={stt_latency_s:.2f}s, "
            f"redis_latency={redis_latency_ms:.1f}ms)"
        )

        # Validate transcription
        if not transcription:
            logging.warning("Received empty transcription. Skipping.")
            return

        # Check Redis for conversation config (set by API)
        config_lookup_start = time.monotonic()
        streaming_tts = False
        conversation_id = None
        try:
            # First, find the conversation_id from the room_name
            conversation_id = await self.redis_client.get(
                f"room:{room_name}:conversation_id"
            )
            if conversation_id:
                conversation_id = conversation_id.decode()
                config_data = await self.redis_client.hgetall(
                    f"conversation:{conversation_id}"
                )
                if config_data:
                    if b"streaming_tts" in config_data:
                        streaming_tts = (
                            config_data[b"streaming_tts"].decode().lower() == "true"
                        )
                    config_lookup_time = time.monotonic() - config_lookup_start
                    logging.info(
                        f"[CONFIG] Retrieved from Redis for conv_id {conversation_id} in {config_lookup_time:.3f}s: "
                        f"streaming_tts={streaming_tts}"
                    )
            else:
                logging.warning(
                    f"No conversation_id found for room {room_name} in Redis."
                )

        except Exception as e:
            logging.warning(f"Failed to retrieve conversation config from Redis: {e}")

        # Use conversation_id as the primary identifier, fallback to room_name
        conv_key = conversation_id or room_name
        await self.ensure_initialized(conv_key, streaming_tts=streaming_tts)

        llm_start_time = time.monotonic()
        ts_llm_start = time.time()
        logging.info(
            f"[LLM_START] → Starting LLM processing at t={llm_start_time:.3f} for: '{transcription}'"
        )

        tts_service = self.adapter.get_tts_service(conv_key)

        # Check if streaming TTS is enabled
        if self.adapter.is_streaming_tts_enabled(conv_key):
            # --- Streaming path: LLM tokens pipe directly into TTS ---
            # Run the blocking LLM generator in a thread-pool so the event loop
            # stays free.  Tokens are forwarded to the async world via a Queue.
            loop = asyncio.get_running_loop()
            token_queue: asyncio.Queue[str | None] = asyncio.Queue()
            full_text_parts: list[str] = []
            finalize_holder: list = []
            llm_error_holder: list[Exception] = []
            llm_end_time_holder: list[float] = []  # [monotonic, wallclock]

            def _run_llm_in_thread():
                try:
                    token_iter, finalize_fn = self.adapter.get_response_stream(
                        conv_key, transcription
                    )
                    finalize_holder.append(finalize_fn)
                    for token in token_iter:
                        full_text_parts.append(token)
                        loop.call_soon_threadsafe(token_queue.put_nowait, token)
                except Exception as exc:
                    llm_error_holder.append(exc)
                finally:
                    # Record LLM end time before signalling done
                    llm_end_time_holder.extend([time.monotonic(), time.time()])
                    loop.call_soon_threadsafe(token_queue.put_nowait, None)  # sentinel

            llm_thread = threading.Thread(
                target=_run_llm_in_thread, daemon=True, name="llm-stream"
            )
            llm_thread.start()

            # Async generator that accumulates tokens and yields text to TTS.
            # First chunk: yield early at a clause boundary (,;:—) or after
            # _FIRST_CHUNK_MIN_WORDS words to minimise TTFA for short responses.
            # Subsequent chunks: yield at sentence boundaries (.!?\n) for natural
            # prosody.
            _SENTENCE_END = re.compile(r"[.!?\n]")
            _CLAUSE_END = re.compile(r"[,;:\u2014]")
            _FIRST_CHUNK_MIN_WORDS = 7

            async def _live_token_gen():
                buffer = ""
                is_first_chunk = True  # early-trigger active until first yield
                is_first_sentence = True  # controls strip_fillers in sanitize
                cancel_ev = self._cancel_events[room_name]
                while True:
                    if cancel_ev.is_set():
                        logging.info(
                            "[INTERRUPT] _live_token_gen: cancel flag set, stopping token stream for room=%s",
                            room_name,
                        )
                        return
                    token = await token_queue.get()
                    if token is None:
                        if llm_end_time_holder:
                            mono_end, wc_end = (
                                llm_end_time_holder[0],
                                llm_end_time_holder[1],
                            )
                            timing_ctx["ts_llm_end"] = wc_end
                            timing_ctx["dur_llm_ms"] = round(
                                (mono_end - llm_start_time) * 1000
                            )
                        break
                    buffer += token

                    # Sentence boundaries always take priority.
                    while True:
                        m = _SENTENCE_END.search(buffer)
                        if not m:
                            break
                        end_idx = m.end()
                        sentence = buffer[:end_idx].strip()
                        if sentence:
                            sentence = sanitize_for_tts(
                                sentence, strip_fillers=is_first_sentence
                            )
                            is_first_sentence = False
                            is_first_chunk = False
                            if sentence:
                                yield sentence
                        buffer = buffer[end_idx:].lstrip()

                    # Early-trigger for the first chunk only: yield at a clause
                    # boundary or once enough words have accumulated.
                    if is_first_chunk:
                        m_clause = _CLAUSE_END.search(buffer)
                        if m_clause:
                            end_idx = m_clause.end()
                            text = buffer[:end_idx].strip()
                            buffer = buffer[end_idx:].lstrip()
                            if text:
                                text = sanitize_for_tts(text, strip_fillers=True)
                                is_first_sentence = False
                                is_first_chunk = False
                                if text:
                                    logging.info(
                                        "[EARLY_TTS] First chunk at clause boundary: '%s'",
                                        text[:60],
                                    )
                                    yield text
                        elif len(buffer.split()) >= _FIRST_CHUNK_MIN_WORDS:
                            last_space = buffer.rfind(" ")
                            if last_space > 0:
                                text = buffer[:last_space].strip()
                                buffer = buffer[last_space:].lstrip()
                                if text:
                                    text = sanitize_for_tts(text, strip_fillers=True)
                                    is_first_sentence = False
                                    is_first_chunk = False
                                    if text:
                                        logging.info(
                                            "[EARLY_TTS] First chunk at word threshold (%d words): '%s'",
                                            _FIRST_CHUNK_MIN_WORDS,
                                            text[:60],
                                        )
                                        yield text

                if buffer.strip():
                    sentence = sanitize_for_tts(
                        buffer.strip(), strip_fillers=is_first_sentence
                    )
                    if sentence:
                        yield sentence

            ts_tts_start = time.time()
            tts_start_time = time.monotonic()

            timing_ctx: dict = {
                "turn_id": turn_id,
                "room_name": room_name,
                "conv_key": conv_key,
                "transcription": transcription,
                "llm_response": "",  # filled in after stream completes
                # Share incremental LLM token accumulation so _stream_tts can
                # emit a complete llm_response in turn_summary without an extra pass.
                "llm_response_parts": full_text_parts,
                "ts_vad_end": ts_vad_end,
                "ts_stt_published": publish_timestamp,
                "ts_thinker_recv": task_start_wallclock,
                "ts_llm_start": ts_llm_start,
                "ts_llm_end": None,  # filled in after stream completes
                "ts_tts_start": ts_tts_start,
                "dur_stt_ms": round(stt_latency_s * 1000) if stt_latency_s else None,
                "dur_redis_ms": round(redis_latency_ms),
                "dur_llm_ms": None,  # filled in after stream completes
            }

            logging.info(
                f"[TTS_START] → Starting streaming LLM→TTS pipeline at t={tts_start_time:.3f}"
            )
            await self._stream_tts(
                conv_key,
                room_name,
                None,
                tts_service,
                timing_ctx,
                text_gen=_live_token_gen(),
            )

            # LLM thread should already be done; join as a safety net
            llm_thread.join(timeout=5)

            if llm_error_holder:
                logging.error(f"[LLM_STREAM_ERROR] {llm_error_holder[0]}")

            response_text = sanitize_for_tts("".join(full_text_parts).strip())
            if not response_text:
                logging.warning("[LLM_STREAM] Empty response from streaming LLM.")
                return

            timing_ctx["llm_response"] = response_text

            dur_llm = timing_ctx.get("dur_llm_ms", "?")
            tts_end_time = time.monotonic()
            logging.info(
                f"[LLM_COMPLETE] ✓ Streaming LLM complete (dur_llm={dur_llm}ms) "
                f"response='{response_text[:80]}...'"
            )
            logging.info(
                f"[TTS_COMPLETE] ✓ Streaming TTS complete (took {tts_end_time - tts_start_time:.3f}s)"
            )

            # Persist the turn to history after TTS has started playing
            if finalize_holder:
                try:
                    finalize_holder[0](response_text)
                except Exception as exc:
                    logging.error(
                        f"[FINALIZE_TURN] Failed to persist streaming turn: {exc}"
                    )

        else:
            # --- Non-streaming (batch) fallback ---
            try:
                turn = self.adapter.process_turn_text_only(conv_key, transcription)
                llm_end_time = time.monotonic()
                ts_llm_end = time.time()
                logging.info(
                    f"[LLM_COMPLETE] ✓ LLM processing complete (took {llm_end_time - llm_start_time:.3f}s)"
                )
            except SafetyEvaluationError as e:
                llm_end_time = time.monotonic()
                ts_llm_end = time.time()
                logging.error(
                    f"[SAFETY] Safety evaluation failed after {llm_end_time - llm_start_time:.3f}s: {e}. "
                    f"Falling back to generic safe response."
                )
                turn = {
                    "system_response": "I'm here with you, but I'm having a little trouble responding right now.",
                    "interaction_type": "chitchat",
                }

            response_text = turn.get("system_response", "")
            if not response_text:
                logging.warning("Adapter returned no response text. Skipping.")
                return

            logging.info(f"[ADAPTER] Response: '{response_text}'")

            tts_start_time = time.monotonic()
            ts_tts_start = time.time()

            timing_ctx = {
                "turn_id": turn_id,
                "room_name": room_name,
                "conv_key": conv_key,
                "transcription": transcription,
                "llm_response": response_text,
                "ts_vad_end": ts_vad_end,
                "ts_stt_published": publish_timestamp,
                "ts_thinker_recv": task_start_wallclock,
                "ts_llm_start": ts_llm_start,
                "ts_llm_end": ts_llm_end,
                "ts_tts_start": ts_tts_start,
                "dur_stt_ms": round(stt_latency_s * 1000) if stt_latency_s else None,
                "dur_redis_ms": round(redis_latency_ms),
                "dur_llm_ms": round((llm_end_time - llm_start_time) * 1000),
            }

            logging.info(
                f"[TTS_START] → Starting batch TTS generation at t={tts_start_time:.3f}"
            )
            await self._batch_tts(conv_key, room_name, response_text, tts_service)
            tts_end_time = time.monotonic()
            ts_tts_complete_wc = time.time()
            ts_tts_first_chunk_wc = (
                ts_tts_complete_wc  # batch: "first audio" == first available audio
            )
            dur_tts_total_ms = round((ts_tts_complete_wc - ts_tts_start) * 1000)
            dur_backend_ttfu_ms = (
                round((ts_tts_complete_wc - ts_vad_end) * 1000) if ts_vad_end else None
            )

            # Capture TurnState fields for logging (read after finalize callbacks may run)
            _turn_state = self.adapter.get_turn_state(conv_key)
            _age_bucket = _turn_state.age_bucket if _turn_state else None
            _safety_flag = _turn_state.safety_flag.value if _turn_state else None
            _safety_tags = (
                [t.value for t in _turn_state.safety_tags] if _turn_state else []
            )

            turn_summary = {
                "event": "turn_summary",
                "conversation_id": conv_key,
                "turn_id": turn_id,
                "room_name": room_name,
                "transcription": transcription,
                "ts_vad_end": ts_vad_end,
                "ts_stt_published": publish_timestamp,
                "ts_thinker_recv": task_start_wallclock,
                "ts_llm_start": ts_llm_start,
                "ts_llm_end": ts_llm_end,
                "ts_tts_start": ts_tts_start,
                "ts_tts_first_chunk": ts_tts_first_chunk_wc,
                "ts_tts_complete": ts_tts_complete_wc,
                "dur_stt_ms": timing_ctx.get("dur_stt_ms"),
                "dur_redis_ms": timing_ctx.get("dur_redis_ms"),
                "dur_llm_ms": timing_ctx.get("dur_llm_ms"),
                "dur_tts_total_ms": dur_tts_total_ms,
                "dur_backend_ttfu_ms": dur_backend_ttfu_ms,
                "llm_response": response_text,
                # Batch TTS publishes a single "audio payload", so TTFA == total here.
                "tts_chunks": 1,
                "tts_bytes": None,
                # TurnState fields for conversation quality analysis
                "age_bucket": _age_bucket,
                "safety_flag": _safety_flag,
                "safety_tags": _safety_tags,
            }

            _append_jsonl(LATENCY_LOG_DIR / "turns.jsonl", turn_summary)
            if ENABLE_CONVERSATION_LATENCY_JSON_LOGGING:
                _append_jsonl(
                    CONVERSATION_LATENCY_LOG_DIR / str(conv_key) / "turns.jsonl",
                    turn_summary,
                )
            logging.info(
                "[TURN_SUMMARY] (batch) Logged turn_id=%s backend_ttfu=%sms llm=%sms",
                turn_id,
                dur_backend_ttfu_ms,
                timing_ctx.get("dur_llm_ms"),
            )
            logging.info(
                f"[TTS_COMPLETE] ✓ Batch TTS complete (took {tts_end_time - tts_start_time:.3f}s)"
            )

        # Log total task processing time
        task_end_time = time.monotonic()
        total_task_time = task_end_time - task_start_time
        logging.info(
            f"[TASK_COMPLETE] ✅ Total task processing: {total_task_time:.3f}s "
            f"(room={room_name})"
        )

    async def _batch_tts(
        self, conversation_id: str, room_name: str, text: str, tts_service
    ):
        """Generate TTS audio in one batch and send it."""
        try:
            # Use the adapter's helper method to generate audio
            audio_bytes = self.adapter._generate_audio(tts_service, text)

            # Ensure it's PCM16 at 16kHz
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
            seg = seg.set_frame_rate(RATE).set_channels(1).set_sample_width(2)
            pcm_audio_bytes = seg.raw_data

            result = {
                "room_name": room_name,  # Use room_name for the bot to identify the message
                "tts_audio_b64": base64.b64encode(pcm_audio_bytes).decode("utf-8"),
            }
            await self.redis_client.publish("jubu_results", json.dumps(result))
            logging.info(
                f"Published batch TTS result for room {room_name} ({len(pcm_audio_bytes)} bytes)"
            )
        except Exception as e:
            logging.error(f"Batch TTS failed: {e}", exc_info=True)
            # Publish error
            await self.redis_client.publish(
                "jubu_results", json.dumps({"room_name": room_name, "error": str(e)})
            )

    async def _stream_tts(
        self,
        conversation_id: str,
        room_name: str,
        text: str | None,
        tts_service,
        timing_ctx: dict | None = None,
        text_gen=None,
    ):
        """Stream TTS audio chunks as they're generated.

        When text_gen (an async generator of text tokens) is provided the
        pipeline feeds tokens directly into the TTS provider so audio starts
        before the LLM has finished generating.  When only text is provided the
        original sentence-split approach is used as a fallback.
        """
        timing_ctx = timing_ctx or {}
        turn_id = timing_ctx.get("turn_id") or uuid.uuid4().hex[:8]
        anchor_name, anchor_ts = _select_user_perceived_ttfa_anchor(timing_ctx)
        ts_tts_start = timing_ctx.get("ts_tts_start") or time.time()
        save_tts_audio = os.getenv("SAVE_TTS_AUDIO", "0") == "1"
        tts_audio_chunks: list[bytes] = []

        # Barge-in: create a threading.Event that mirrors the asyncio cancel event
        # so ElevenLabs daemon threads can close their HTTP response early.
        tts_cancel_thread_event = threading.Event()

        async def _watch_cancel():
            """Poll the asyncio cancel event and set the threading counterpart."""
            cancel_ev = self._cancel_events[room_name]
            while True:
                if cancel_ev.is_set():
                    tts_cancel_thread_event.set()
                    return
                await asyncio.sleep(0.05)

        watch_task = asyncio.create_task(_watch_cancel())

        try:
            stream_id = f"{conversation_id}-{uuid.uuid4().hex}"

            await self.redis_client.publish(
                "jubu_tts_stream",
                json.dumps(
                    {
                        "room_name": room_name,
                        "event": "stream_start",
                        "stream_id": stream_id,
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "text": text or "",
                        # Backend proxy of end-of-user-speech to enable
                        # closer user-perceived TTFA estimation in livekit_bot.
                        "anchor_name": anchor_name,
                        "anchor_ts": anchor_ts,
                    }
                ),
            )
            # Register this as the active stream for the room so that
            # _listen_interrupts() can match incoming interrupt events correctly.
            self._active_stream_id_by_room[room_name] = stream_id
            logging.info(
                f"[TTS_STREAM] Starting for room {room_name} stream_id={stream_id} turn_id={turn_id}"
            )

            if text_gen is not None:
                # Streaming path: _live_token_gen() yields complete sentences;
                # the ElevenLabs provider synthesizes each one immediately via
                # the /stream endpoint without any internal re-buffering.
                async def text_iter():
                    async for token in text_gen:
                        yield token

            else:
                # Fallback: full text already available, split into sentences.
                def _split_sentences(t: str):
                    parts = []
                    buf = []
                    for ch in t:
                        buf.append(ch)
                        if ch in ".!?\n":
                            part = "".join(buf).strip()
                            if part:
                                parts.append(part)
                            buf = []
                    tail = "".join(buf).strip()
                    if tail:
                        parts.append(tail)
                    return parts or [t]

                sentences = _split_sentences(text or "")

                async def text_iter():
                    for s in sentences:
                        yield s

            seq = 0
            total_bytes = 0
            ts_tts_first_chunk: float | None = None
            tts_start_mono = time.monotonic()
            cancel_ev = self._cancel_events[room_name]

            # Stream audio from TTS service.
            # Pass cancel_event so ElevenLabs threads can close HTTP responses early.
            async for audio_chunk in tts_service.stream_audio(
                text_iter(), cancel_event=tts_cancel_thread_event
            ):
                if not audio_chunk:
                    continue

                # Barge-in: stop publishing chunks if the room was interrupted
                if cancel_ev.is_set():
                    logging.info(
                        "[INTERRUPT] _stream_tts: cancel flag set, stopping TTS for room=%s stream_id=%s",
                        room_name,
                        stream_id,
                    )
                    break

                chunk_recv_mono = time.monotonic()

                # The audio_chunk from ElevenLabs streaming is already raw PCM 16-bit 16kHz.
                pcm_chunk = audio_chunk
                total_bytes += len(pcm_chunk)
                if save_tts_audio:
                    tts_audio_chunks.append(pcm_chunk)

                # TTFA (Time To First Audio) for first chunk
                if seq == 0:
                    ts_tts_first_chunk = time.time()
                    ttfa_s = chunk_recv_mono - tts_start_mono
                    dur_llm_ms = timing_ctx.get("dur_llm_ms")
                    llm_info = (
                        f"{dur_llm_ms / 1000:.3f}s"
                        if dur_llm_ms is not None
                        else "streaming (overlapped)"
                    )
                    logging.info(
                        f"[TTS_TTFA] ✨ First audio chunk generated in {ttfa_s:.3f}s "
                        f"(LLM={llm_info}, TTS TTFA={ttfa_s:.3f}s)"
                    )

                # Publish chunk to Redis (include turn_id for correlation)
                publish_start = time.monotonic()
                await self.redis_client.publish(
                    "jubu_tts_stream",
                    json.dumps(
                        {
                            "room_name": room_name,
                            "event": "chunk",
                            "stream_id": stream_id,
                            "turn_id": turn_id,
                            "seq": seq,
                            "audio_b64": base64.b64encode(pcm_chunk).decode("utf-8"),
                            "bytes": len(pcm_chunk),
                        }
                    ),
                )
                publish_took = time.monotonic() - publish_start

                audio_duration = len(pcm_chunk) / (RATE * 2)  # PCM16 at 16kHz
                logging.debug(
                    f"[TTS_PUBLISH] Chunk #{seq} → Redis: {len(pcm_chunk)} bytes, "
                    f"audio_dur={audio_duration:.3f}s, publish_took={publish_took:.3f}s"
                )

                if seq == 0:
                    logging.info(
                        f"[TTS_STREAM] First chunk sent ({len(pcm_chunk)} bytes)"
                    )
                seq += 1

            ts_tts_complete = time.time()

            # Signal stream complete (include turn_id)
            await self.redis_client.publish(
                "jubu_tts_stream",
                json.dumps(
                    {
                        "room_name": room_name,
                        "event": "stream_complete",
                        "stream_id": stream_id,
                        "turn_id": turn_id,
                        "total_bytes": total_bytes,
                        "chunks": seq,
                    }
                ),
            )
            logging.info(
                f"[TTS_STREAM] Complete: {seq} chunks, {total_bytes} bytes stream_id={stream_id}"
            )

            # Optionally save TTS audio for this turn to run folder (e.g. latency/runs/<run-name>/tts_audio/)
            if save_tts_audio and tts_audio_chunks:
                tts_audio_dir = LATENCY_LOG_DIR / "tts_audio"
                tts_audio_dir.mkdir(parents=True, exist_ok=True)
                wav_path = tts_audio_dir / f"{turn_id}.wav"
                try:
                    with wave.open(str(wav_path), "wb") as wav_file:
                        wav_file.setnchannels(1)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(RATE)
                        for chunk in tts_audio_chunks:
                            wav_file.writeframes(chunk)
                    logging.info("[TTS_SAVE] Saved turn audio to %s", wav_path)
                except Exception as e:
                    logging.warning("[TTS_SAVE] Failed to write %s: %s", wav_path, e)

            # Emit structured turn summary to LATENCY_LOG_DIR/turns.jsonl
            ts_tts_start_wc: float = ts_tts_start
            dur_tts_total_ms = round((ts_tts_complete - ts_tts_start_wc) * 1000)
            ts_vad_end = timing_ctx.get("ts_vad_end")
            dur_backend_ttfu_ms = (
                round((ts_tts_complete - ts_vad_end) * 1000) if ts_vad_end else None
            )
            llm_response_text = timing_ctx.get("llm_response", "")
            if not llm_response_text:
                response_parts = timing_ctx.get("llm_response_parts")
                if isinstance(response_parts, list):
                    llm_response_text = "".join(
                        p for p in response_parts if isinstance(p, str)
                    ).strip()
            # Capture TurnState fields for logging (read after finalize callbacks may run)
            _turn_state = self.adapter.get_turn_state(timing_ctx.get("conv_key", ""))
            _age_bucket = _turn_state.age_bucket if _turn_state else None
            _safety_flag = _turn_state.safety_flag.value if _turn_state else None
            _safety_tags = (
                [t.value for t in _turn_state.safety_tags] if _turn_state else []
            )

            turn_summary = {
                "event": "turn_summary",
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "room_name": room_name,
                "transcription": timing_ctx.get("transcription", ""),
                "ts_vad_end": ts_vad_end,
                "ts_stt_published": timing_ctx.get("ts_stt_published"),
                "ts_thinker_recv": timing_ctx.get("ts_thinker_recv"),
                "ts_llm_start": timing_ctx.get("ts_llm_start"),
                "ts_llm_end": timing_ctx.get("ts_llm_end"),
                "ts_tts_start": ts_tts_start_wc,
                "ts_tts_first_chunk": ts_tts_first_chunk,
                "ts_tts_complete": ts_tts_complete,
                "dur_stt_ms": timing_ctx.get("dur_stt_ms"),
                "dur_redis_ms": timing_ctx.get("dur_redis_ms"),
                "dur_llm_ms": timing_ctx.get("dur_llm_ms"),
                "dur_tts_total_ms": dur_tts_total_ms,
                "dur_backend_ttfu_ms": dur_backend_ttfu_ms,
                "llm_response": llm_response_text,
                "tts_chunks": seq,
                "tts_bytes": total_bytes,
                # TurnState fields for conversation quality analysis
                "age_bucket": _age_bucket,
                "safety_flag": _safety_flag,
                "safety_tags": _safety_tags,
            }
            _append_jsonl(LATENCY_LOG_DIR / "turns.jsonl", turn_summary)
            if ENABLE_CONVERSATION_LATENCY_JSON_LOGGING:
                _append_jsonl(
                    CONVERSATION_LATENCY_LOG_DIR / str(conversation_id) / "turns.jsonl",
                    turn_summary,
                )
            logging.info(
                "[TURN_SUMMARY] Logged turn_id=%s backend_ttfu=%sms llm=%sms",
                turn_id,
                dur_backend_ttfu_ms,
                timing_ctx.get("dur_llm_ms"),
            )

        except Exception as e:
            logging.error(f"Streaming TTS failed: {e}", exc_info=True)
            # Signal error
            await self.redis_client.publish(
                "jubu_tts_stream",
                json.dumps(
                    {
                        "room_name": room_name,
                        "event": "error",
                        "stream_id": locals().get("stream_id"),
                        "turn_id": turn_id,
                        "error": str(e),
                    }
                ),
            )
        finally:
            # Deregister this stream so stale interrupts arriving after the
            # stream ends cannot cancel the next turn.
            self._active_stream_id_by_room.pop(room_name, None)
            # Cancel the cancel-event watcher task
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task

    async def run(self):
        tasks_pubsub = self.redis_client.pubsub()
        await tasks_pubsub.subscribe("jubu_tasks")
        logging.info("Thinker is running, subscribed to 'jubu_tasks' channel.")

        print("[THINKER_READY]", flush=True)
        conversation_event_task = asyncio.create_task(
            self._listen_conversation_events()
        )
        interrupt_task = asyncio.create_task(self._listen_interrupts())

        try:
            async for message in tasks_pubsub.listen():
                if message["type"] == "message":
                    msg_recv_time = time.monotonic()
                    raw = message["data"]
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="replace")
                    try:
                        task = json.loads(raw)
                        logging.info(
                            f"[REDIS_MSG] Message received at t={msg_recv_time:.3f}, dispatching to process_task"
                        )
                        await self.process_task(task)
                    except Exception as e:
                        logging.error(f"Error processing task: {e}", exc_info=True)
        finally:
            conversation_event_task.cancel()
            interrupt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await conversation_event_task
            with contextlib.suppress(asyncio.CancelledError):
                await interrupt_task
            with contextlib.suppress(Exception):
                await tasks_pubsub.unsubscribe("jubu_tasks")


if __name__ == "__main__":
    thinker = Thinker()
    asyncio.run(thinker.run())
