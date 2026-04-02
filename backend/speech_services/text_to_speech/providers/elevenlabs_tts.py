import asyncio
import base64
import json
import logging
import os
import tempfile
import threading
import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import requests
import websockets
from dotenv import load_dotenv

from speech_services.text_to_speech.tts_provider import TTSProvider

load_dotenv()

logger = logging.getLogger(__name__)

# PCM chunk size for iter_content when streaming audio from ElevenLabs.
# Smaller values reduce TTFA slightly; larger values reduce overhead per chunk.
_PCM_CHUNK_SIZE = int(os.getenv("ELEVENLABS_PCM_CHUNK_SIZE", "4096"))


class ElevenLabsSpeaker(TTSProvider):
    """
    Text-to-speech via ElevenLabs API.

    Streaming path: uses the /stream REST endpoint with stream=True so that
    raw PCM16 bytes are yielded as they arrive (first bytes ~100-150ms) rather
    than waiting for the full synthesis (~300-500ms).

    Configurable via env vars:
        ELEVENLABS_MODEL_ID              (default: eleven_flash_v2_5)
        ELEVENLABS_OPTIMIZE_LATENCY      (default: 3, range 0-4)
        ELEVENLABS_STABILITY             (default: 0.5, range 0.0-1.0)
        ELEVENLABS_SIMILARITY_BOOST      (default: 0.5, range 0.0-1.0)
        ELEVENLABS_SPEED                 (default: 1.0, range 0.7-1.2)
        ELEVENLABS_STYLE                 (default: 0.0, range 0.0-1.0)
        ELEVENLABS_USE_SPEAKER_BOOST     (default: false)
        ELEVENLABS_INTER_SENTENCE_GAP_MS (default: 0, silence in ms between streamed sentences)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = "bIQlQ61Q7WgbyZAL7IWj",
    ):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ElevenLabs API key is required. "
                "Set it directly or via ELEVENLABS_API_KEY environment variable."
            )

        self.voice_id = voice_id
        # eleven_flash_v2_5 is optimised for real-time / low-latency use cases.
        # Override with ELEVENLABS_MODEL_ID to A/B test other models.
        self.model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
        # Level 3: max latency opts with text normaliser still enabled.
        # Level 4: also disables normaliser (saves a few ms but may mispronounce numbers).
        self.optimize_latency = int(os.getenv("ELEVENLABS_OPTIMIZE_LATENCY", "3"))
        self.base_url = "https://api.elevenlabs.io/v1"

        # ── Voice settings (all overridable via env vars) ──
        # 0.0 = max variation / emotional range, 1.0 = most stable / monotone
        self.stability = float(os.getenv("ELEVENLABS_STABILITY", "0.5"))
        # 0.0 = least similar to original voice, 1.0 = most faithful clone
        self.similarity_boost = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.5"))
        # 0.7 – 1.2; 1.0 = normal pace
        self.speed = float(os.getenv("ELEVENLABS_SPEED", "1.0"))
        # 0.0 – 1.0; amplifies the speaker's style. >0 adds latency.
        self.style = float(os.getenv("ELEVENLABS_STYLE", "0.0"))
        # Boosts similarity to original speaker; adds a little latency.
        self.use_speaker_boost = os.getenv(
            "ELEVENLABS_USE_SPEAKER_BOOST", "false"
        ).lower() in ("true", "1", "yes")
        # Silence injected between streamed sentences (PCM16 16kHz mono).
        # Helps when speed < 1.0 makes the gap between sentences feel too tight.
        gap_ms = int(os.getenv("ELEVENLABS_INTER_SENTENCE_GAP_MS", "0"))
        # PCM16 16kHz mono: 1 ms = 16 samples × 2 bytes = 32 bytes
        self._inter_sentence_silence = b"\x00" * (gap_ms * 32) if gap_ms > 0 else b""

        # Shared HTTP session for connection reuse
        self._session = requests.Session()
        self._session.headers.update({"xi-api-key": self.api_key})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_voice_settings(
        self,
        stability: Optional[float] = None,
        similarity_boost: Optional[float] = None,
        speed: Optional[float] = None,
        style: Optional[float] = None,
        use_speaker_boost: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Build a voice_settings dict, falling back to instance defaults."""
        return {
            "stability": stability if stability is not None else self.stability,
            "similarity_boost": (
                similarity_boost
                if similarity_boost is not None
                else self.similarity_boost
            ),
            "speed": speed if speed is not None else self.speed,
            "style": style if style is not None else self.style,
            "use_speaker_boost": (
                use_speaker_boost
                if use_speaker_boost is not None
                else self.use_speaker_boost
            ),
        }

    # ------------------------------------------------------------------
    # TTSProvider interface -- batch methods
    # ------------------------------------------------------------------

    def list_available_voices(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/voices"
        response = self._session.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json().get("voices", [])

    def text_to_speech(
        self,
        text: str,
        voice_id: Optional[str] = None,
        stability: Optional[float] = None,
        similarity_boost: Optional[float] = None,
    ) -> bytes:
        voice_id = voice_id or self.voice_id
        url = f"{self.base_url}/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        data = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": self._build_voice_settings(
                stability=stability, similarity_boost=similarity_boost
            ),
        }
        start = time.monotonic()
        response = self._session.post(url, json=data, headers=headers)
        elapsed = time.monotonic() - start
        try:
            response.raise_for_status()
        except Exception as e:
            logger.error(f"ELEVENLABS: synth error after {elapsed:.3f}s: {e}")
            raise
        logger.info(
            f"ELEVENLABS: synth ok in {elapsed:.3f}s, bytes={len(response.content)}"
        )
        return response.content

    def save_to_file(self, audio_data: bytes, file_path: str) -> str:
        with open(file_path, "wb") as f:
            f.write(audio_data)
        return file_path

    def speak(
        self,
        text: str,
        voice_id: Optional[str] = None,
        stability: Optional[float] = None,
        similarity_boost: Optional[float] = None,
    ) -> None:
        audio_data = self.text_to_speech(text, voice_id, stability, similarity_boost)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_filename = temp_file.name
        temp_file.close()
        try:
            self.save_to_file(audio_data, temp_filename)
        finally:
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    # ------------------------------------------------------------------
    # Streaming internals
    # ------------------------------------------------------------------

    def _stream_pcm16_chunks(
        self,
        text: str,
        voice: str,
        stability: Optional[float] = None,
        similarity_boost: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[bytes]:
        """
        Synchronous generator that calls the ElevenLabs /stream endpoint with
        stream=True and yields raw PCM16 16kHz mono chunks as they arrive over
        the wire.  Intended to run inside a daemon thread so the event loop
        stays free.

        If cancel_event is provided and set, the HTTP response is closed
        immediately and the generator stops yielding chunks.
        """
        url = f"{self.base_url}/text-to-speech/{voice}/stream"
        params = {
            "output_format": "pcm_16000",
            "optimize_streaming_latency": str(self.optimize_latency),
        }
        headers = {
            "Accept": "application/octet-stream",
            "Content-Type": "application/json",
        }
        data = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": self._build_voice_settings(
                stability=stability, similarity_boost=similarity_boost
            ),
        }
        start = time.monotonic()
        resp = self._session.post(
            url, params=params, json=data, headers=headers, stream=True
        )
        resp.raise_for_status()
        first = True
        for chunk in resp.iter_content(chunk_size=_PCM_CHUNK_SIZE):
            if cancel_event and cancel_event.is_set():
                logger.info("ELEVENLABS: cancel_event set, closing stream early")
                resp.close()
                return
            if chunk:
                if first:
                    logger.info(
                        f"ELEVENLABS: /stream first chunk in {time.monotonic()-start:.3f}s "
                        f"size={len(chunk)}"
                    )
                    first = False
                yield chunk
        logger.info(f"ELEVENLABS: /stream complete in {time.monotonic()-start:.3f}s")

    # ------------------------------------------------------------------
    # Streaming TTS (TTSProvider interface)
    # ------------------------------------------------------------------

    async def stream_text_to_speech(
        self,
        text_stream: AsyncIterator[str],
        voice_id: Optional[str] = None,
        stability: Optional[float] = None,
        similarity_boost: Optional[float] = None,
        **kwargs,
    ) -> AsyncIterator[bytes]:
        """
        Stream text to speech via the ElevenLabs WebSocket API.

        Opens a single persistent WebSocket connection per turn and feeds text
        chunks as they arrive from text_stream.  Audio chunks (PCM16 16kHz mono)
        are yielded as they come back from the server.

        This eliminates the per-sentence HTTP connection overhead (~100-200ms)
        of the previous per-sentence POST approach, and allows ElevenLabs to
        start generating audio before a full sentence is available.

        Keyword args:
          cancel_event (threading.Event): if set, stops streaming mid-turn.
              Used for barge-in cancellation.
          min_chars, flush_punct: accepted and ignored (legacy compat).
        """
        voice = voice_id or self.voice_id
        cancel_event: Optional[threading.Event] = kwargs.get("cancel_event")

        uri = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{voice}/stream-input"
            f"?model_id={self.model_id}"
            f"&output_format=pcm_16000"
            f"&optimize_streaming_latency={self.optimize_latency}"
        )

        audio_queue: asyncio.Queue = asyncio.Queue()

        async def _ws_worker() -> None:
            """Manages the WebSocket lifecycle: send text in, put audio into queue."""
            try:
                async with websockets.connect(
                    uri,
                    additional_headers={"xi-api-key": self.api_key},
                ) as ws:
                    # Initial message carries voice settings and generation config.
                    # chunk_length_schedule controls when ElevenLabs flushes audio;
                    # the first value (120 chars) keeps TTFA low.
                    await ws.send(
                        json.dumps(
                            {
                                "text": " ",
                                "voice_settings": self._build_voice_settings(
                                    stability=stability,
                                    similarity_boost=similarity_boost,
                                ),
                                "generation_config": {
                                    "chunk_length_schedule": [120, 160, 250, 290]
                                },
                            }
                        )
                    )

                    async def _send_text() -> None:
                        try:
                            async for chunk in text_stream:
                                if cancel_event and cancel_event.is_set():
                                    break
                                chunk = chunk.strip()
                                if chunk:
                                    await ws.send(
                                        json.dumps(
                                            {
                                                "text": chunk + " ",
                                                "try_trigger_generation": True,
                                            }
                                        )
                                    )
                            # Empty string flushes remaining audio and signals EOS.
                            await ws.send(json.dumps({"text": ""}))
                        except Exception as exc:
                            logger.error(f"ELEVENLABS WS: send error: {exc}")

                    send_task = asyncio.create_task(_send_text())

                    first = True
                    t0 = time.monotonic()
                    chunk_count = 0
                    total_bytes = 0

                    try:
                        async for message in ws:
                            if cancel_event and cancel_event.is_set():
                                logger.info(
                                    "ELEVENLABS WS: cancel_event set, closing stream"
                                )
                                break
                            if isinstance(message, bytes):
                                audio_bytes = message
                            else:
                                data = json.loads(message)
                                raw = data.get("audio")
                                if not raw:
                                    if data.get("isFinal"):
                                        logger.info(
                                            "ELEVENLABS WS: stream complete in "
                                            f"{time.monotonic() - t0:.3f}s "
                                            f"chunks={chunk_count} bytes={total_bytes}"
                                        )
                                        break
                                    continue
                                audio_bytes = base64.b64decode(raw)

                            if first:
                                logger.info(
                                    f"ELEVENLABS WS: first audio chunk in "
                                    f"{time.monotonic() - t0:.3f}s "
                                    f"size={len(audio_bytes)}"
                                )
                                first = False
                            chunk_count += 1
                            total_bytes += len(audio_bytes)
                            audio_queue.put_nowait(audio_bytes)
                    finally:
                        await send_task

            except Exception as exc:
                logger.error(f"ELEVENLABS WS: connection error: {exc}")
            finally:
                audio_queue.put_nowait(None)  # sentinel to stop consumer

        ws_task = asyncio.create_task(_ws_worker())

        try:
            while True:
                chunk = await audio_queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            if not ws_task.done():
                ws_task.cancel()
                try:
                    await ws_task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    speaker = ElevenLabsSpeaker()

    voices = speaker.list_available_voices()
    print("Available voices:")
    for voice in voices:
        print(f"- {voice['name']} (ID: {voice['voice_id']})")

    speaker.speak("Hello! This is a test of the ElevenLabs text to speech API.")

    audio_data = speaker.text_to_speech("This is a test of saving speech to a file.")
    speaker.save_to_file(audio_data, "test_speech.mp3")
    print("Speech saved to test_speech.mp3")
