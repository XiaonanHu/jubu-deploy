import asyncio
import logging
import os
import sys
import tempfile
import time
from contextlib import suppress
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from google.api_core import exceptions as google_exceptions
from google.cloud import speech_v1 as speech
from google.oauth2 import service_account

from speech_services.speech_to_text.stt_provider import STTProvider

logger = logging.getLogger(__name__)


class GoogleTranscriber(STTProvider):
    """
    A class to handle microphone recording and transcription using Google Speech-to-Text API.
    """

    def __init__(
        self, credentials_path: Optional[str] = None, language_code: str = "en-US"
    ):
        """
        Initialize the transcriber with Google Speech-to-Text credentials.

        Args:
            credentials_path: Path to the Google Cloud service account JSON file.
                             If None, will try to use GOOGLE_APPLICATION_CREDENTIALS env variable.
            language_code: The language code for transcription (default: en-US)
        """
        if credentials_path:
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_path
            )
            self.client = speech.SpeechAsyncClient(credentials=self.credentials)
        else:
            # This will be None, but the clients will find credentials from the environment.
            self.credentials = None
            self.client = speech.SpeechAsyncClient()

        self.language_code = language_code

        # Default audio recording parameters
        self.sample_rate = 16000
        self.channels = 1
        self.record_seconds = 5

    async def stream_transcribe(
        self,
        audio_chunk_iterator: AsyncGenerator[bytes, None],
        adaptation_phrases: Optional[List[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Asynchronously transcribe an audio stream using Google STT.

        All work happens on the current event-loop – no helper threads – so we
        avoid cross-loop dead-locks and keep the behaviour identical between
        unit tests and production.
        """

        # --- Build adaptation / recognition configs ---------------------------------
        adaptation_config = None
        if adaptation_phrases:
            phrases = [p for p in adaptation_phrases if p and len(p) <= 100]
            if phrases:
                adaptation_config = speech.SpeechAdaptation(
                    phrase_sets=[
                        speech.PhraseSet(
                            phrases=[
                                speech.PhraseSet.Phrase(value=p, boost=2.5)
                                for p in phrases
                            ]
                        )
                    ]
                )

        recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            language_code=self.language_code,
            enable_automatic_punctuation=True,
            adaptation=adaptation_config,
        )

        streaming_config = speech.StreamingRecognitionConfig(
            config=recognition_config,
            interim_results=True,
            single_utterance=False,  # Changed to False for continuous streaming with external VAD
        )
        with suppress(AttributeError, ValueError):
            streaming_config.enable_partial_results_stabilization = True
        with suppress(AttributeError, ValueError):
            stability_level = getattr(
                speech.StreamingRecognitionConfig, "StabilityLevel", None
            )
            if stability_level is not None:
                streaming_config.stability_threshold = stability_level.HIGH
            else:
                streaming_config.stability_threshold = 0.85

        # Timing markers
        rpc_start = time.monotonic()
        first_interim_dt: Optional[float] = None
        audio_last_sent_at: float = 0.0
        audio_stream_closed_at: float = 0.0

        # --- Helper: async generator that yields raw audio chunks -------------------
        async def request_generator():
            nonlocal audio_last_sent_at, audio_stream_closed_at
            msg = "GOOGLE-STT: ✅ request_generator() STARTED - generator is being consumed!"
            logger.info(msg)
            print(msg, flush=True)

            # DEBUG: Log the config we are about to send
            msg = f"GOOGLE-STT: 🔍 Config check -> Encoding: LINEAR16, SampleRate: {self.sample_rate}, Lang: {self.language_code}"
            logger.info(msg)
            print(msg, flush=True)

            # 1) configuration message
            yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)
            logger.info(
                "GOOGLE-STT: ✅ Config SENT, now waiting for audio chunks from audio_chunk_iterator..."
            )

            # 2) streamed audio with keepalive silence
            chunk_count = 0
            total_bytes = 0
            keepalive_logged = False
            keepalive_interval_s = float(os.getenv("GOOGLE_STT_KEEPALIVE_S", "0.5"))
            silence_frame = b"\x00" * int(
                self.sample_rate * 2 * 0.02
            )  # 20ms PCM16 @ 16kHz
            iterator = audio_chunk_iterator.__aiter__()
            pending_next: Optional[asyncio.Task] = asyncio.create_task(
                iterator.__anext__()
            )

            while True:
                try:
                    done, _ = await asyncio.wait(
                        {pending_next},
                        timeout=keepalive_interval_s,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if pending_next not in done:
                        # Send short silence to keep stream alive during idle periods
                        if not keepalive_logged:
                            logger.info(
                                "GOOGLE-STT: sending keepalive silence every %.2fs during idle audio",
                                keepalive_interval_s,
                            )
                            keepalive_logged = True
                        audio_last_sent_at = time.monotonic()
                        total_bytes += len(silence_frame)
                        yield speech.StreamingRecognizeRequest(
                            audio_content=silence_frame
                        )
                        continue

                    # Consume the completed task result, and immediately queue the next read.
                    try:
                        chunk = pending_next.result()
                    except StopAsyncIteration:
                        break
                    pending_next = asyncio.create_task(iterator.__anext__())
                except asyncio.CancelledError:
                    if pending_next and not pending_next.done():
                        pending_next.cancel()
                    raise

                if not chunk:
                    # Skip empty sentinel frames
                    continue

                chunk_count += 1
                total_bytes += len(chunk)
                audio_last_sent_at = time.monotonic()

                if chunk_count == 1:
                    # DEBUG: Log detailed format info for the first chunk
                    try:
                        preview = (
                            chunk[:10].hex()
                            if isinstance(chunk, (bytes, bytearray))
                            else "N/A"
                        )
                        msg = (
                            f"GOOGLE-STT: 🔍 FIRST CHUNK ANALYSIS:\n"
                            f"  - Type: {type(chunk)}\n"
                            f"  - Length: {len(chunk)} bytes\n"
                            f"  - First 10 bytes: {preview}\n"
                            f"  - Expected: bytes/bytearray of PCM16 (len should be even)"
                        )
                        logger.info(msg)
                        print(msg, flush=True)

                        if len(chunk) % 2 != 0:
                            logger.error(
                                "GOOGLE-STT: ⚠️ WARNING: Chunk length is ODD! PCM16 should be even aligned."
                            )
                    except Exception as e:
                        logger.error(f"GOOGLE-STT: Error logging chunk info: {e}")
                # IMPORTANT: send every chunk (not just the first one)
                yield speech.StreamingRecognizeRequest(audio_content=chunk)

            # Upstream closed (we saw sentinel and iterator ended)
            audio_stream_closed_at = time.monotonic()
            logger.info(
                "GOOGLE-STT: ✅ Audio stream closed by upstream. Sent %d chunks (%d bytes total) over %.3fs",
                chunk_count,
                total_bytes,
                (audio_stream_closed_at - rpc_start),
            )

        # --- Call Google async client ------------------------------------------------
        try:
            logger.info("STT-ASYNC: Starting Google streaming_recognize() call.")

            # Create the request generator
            requests_gen = request_generator()

            # DEBUG: Print data before calling the hanging function
            print(f"GOOGLE-STT: 🔍 PRE-CALL CHECK:", flush=True)
            print(f"  - Generator type: {type(requests_gen)}", flush=True)
            print(f"  - Client type: {type(self.client)}", flush=True)
            print(f"  - Streaming Config: {streaming_config}", flush=True)
            print(f"  - Calling streaming_recognize now...", flush=True)

            # Call the method. Depending on library version, this might return:
            # 1. An async iterable directly
            # 2. A coroutine that returns an async iterable
            # 3. A coroutine that returns a response iterator
            call_result = self.client.streaming_recognize(requests=requests_gen)

            responses = call_result
            if asyncio.iscoroutine(call_result):
                logger.info(
                    "STT-ASYNC: streaming_recognize returned a coroutine, awaiting it with 10s timeout..."
                )
                response_task = asyncio.create_task(call_result)
                try:
                    # Use shield to avoid cancelling the gRPC call on timeout
                    responses = await asyncio.wait_for(
                        asyncio.shield(response_task), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "STT-ASYNC: Connection taking >10s; continuing to wait without cancelling the call."
                    )
                    responses = await response_task

            logger.debug("STT-ASYNC: Got response object type: %s", type(responses))

            # Get the iterator explicitly
            if hasattr(responses, "__aiter__"):
                response_iterator = responses.__aiter__()
            else:
                # Fallback if it's already an iterator or something else
                response_iterator = responses

            logger.info("STT-ASYNC: ✅ Response iterator obtained; awaiting results...")
            first_response_logged = False

            # Iterate the rest
            async for response in response_iterator:
                if not first_response_logged:
                    logger.info(
                        "STT-ASYNC: ✅ First response received from Google (results=%d)",
                        len(response.results),
                    )
                    first_response_logged = True

                # Google can send multiple results per response (one per audio
                # segment).  Concatenate them so the caller always sees the
                # full utterance text instead of only the last segment.
                combined_parts: list[str] = []
                all_final = True
                for result in response.results:
                    transcript = result.alternatives[0].transcript
                    if transcript:
                        combined_parts.append(transcript)
                    if not result.is_final:
                        all_final = False

                    if not result.is_final and first_interim_dt is None:
                        first_interim_dt = time.monotonic() - rpc_start
                        logger.info(
                            f"LATENCY-b| stt.google.first_interim | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int(first_interim_dt*1000)}"
                        )
                    if result.is_final:
                        final_dt = time.monotonic() - rpc_start
                        lag_after_audio_close = None
                        if audio_stream_closed_at > 0:
                            lag_after_audio_close = (
                                time.monotonic() - audio_stream_closed_at
                            )
                            logger.info(
                                f"LATENCY-b| stt.google.final_after_audio_close | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int(lag_after_audio_close*1000)}"
                            )
                        else:
                            logger.info("GOOGLE-STT: final received at %.3fs", final_dt)

                combined_text = " ".join(combined_parts).strip()
                if combined_text:
                    yield {"text": combined_text, "is_final": all_final}

        except google_exceptions.OutOfRange as e:
            logger.warning(
                "STT-ASYNC: Google stream terminated with OutOfRange (likely audio timeout). Details: %s",
                e,
            )
        except asyncio.CancelledError:
            logger.error(
                "STT-ASYNC: streaming_recognize task cancelled by upstream (possibly VAD finished before Google replied)."
            )
            raise
        except Exception as e:
            logger.error(
                "STT-ASYNC: Error during streaming_recognize: %s", e, exc_info=True
            )
            raise

    def record_audio(self, duration: Optional[int] = None) -> str:
        if duration is not None:
            self.record_seconds = duration

        recording = sd.rec(
            int(self.record_seconds * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
        )
        sd.wait()

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_filename = temp_file.name
        temp_file.close()
        sf.write(temp_filename, recording, self.sample_rate)
        return temp_filename

    def record_audio_continuous(
        self, silence_threshold: float = 0.03, silence_duration: float = 1.0
    ) -> str:
        chunk_duration = 0.1
        chunk_size = int(self.sample_rate * chunk_duration)

        audio_data = []
        silence_counter = 0
        has_speech = False
        recording_done = False

        def audio_callback(indata, frames, time_info, status):
            nonlocal silence_counter, has_speech, recording_done
            volume_norm = np.linalg.norm(indata) / np.sqrt(frames)
            audio_data.append(indata.copy())

            if volume_norm < silence_threshold:
                silence_counter += chunk_duration
                if has_speech and silence_counter >= silence_duration:
                    recording_done = True
                    raise sd.CallbackStop
            else:
                silence_counter = 0
                has_speech = True

        stream = sd.InputStream(
            callback=audio_callback,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=chunk_size,
        )

        try:
            with stream:
                max_record_time = 30
                start_time = time.time()
                while not recording_done and time.time() - start_time < max_record_time:
                    sd.sleep(10)
        finally:
            sys.stdout.write("\r")
            sys.stdout.flush()

        if not has_speech or not audio_data:
            return ""

        audio_data = np.concatenate(audio_data, axis=0)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_filename = temp_file.name
        temp_file.close()
        sf.write(temp_filename, audio_data, self.sample_rate)
        return temp_filename

    def transcribe_audio(self, audio_file: str) -> str:
        if (
            not audio_file
            or not os.path.exists(audio_file)
            or os.path.getsize(audio_file) == 0
        ):
            return ""

        with open(audio_file, "rb") as audio_file_obj:
            content = audio_file_obj.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            language_code=self.language_code,
            enable_automatic_punctuation=True,
        )

        try:
            client = speech.SpeechClient(credentials=self.credentials)
            response = client.recognize(config=config, audio=audio)
            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript
            return transcript
        except Exception as e:
            if os.path.exists(audio_file):
                os.remove(audio_file)
            raise RuntimeError(f"Transcription failed: {str(e)}")

    def transcribe_from_bytes(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""

            audio = speech.RecognitionAudio(content=audio_bytes)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language_code,
                enable_automatic_punctuation=True,
            )
        client = speech.SpeechClient(credentials=self.credentials)
        response = client.recognize(config=config, audio=audio)
        if response.results:
            return response.results[0].alternatives[0].transcript
        return ""

    def record_and_transcribe(self, duration: Optional[int] = None) -> str:
        temp_filename = self.record_audio(duration)
        try:
            return self.transcribe_audio(temp_filename)
        finally:
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def record_and_transcribe_continuous(
        self, silence_threshold: float = 0.03, silence_duration: float = 1.0
    ) -> str:
        temp_filename = self.record_audio_continuous(
            silence_threshold, silence_duration
        )
        try:
            if not temp_filename:
                return ""
            return self.transcribe_audio(temp_filename)
        finally:
            if temp_filename and os.path.exists(temp_filename):
                os.unlink(temp_filename)


# Example usage
# if __name__ == "__main__":
#     # You can specify the path to your credentials file directly
#     # transcriber = GoogleTranscriber(credentials_path="path/to/your-credentials.json")

#     # Or set the GOOGLE_APPLICATION_CREDENTIALS environment variable
#     transcriber = GoogleTranscriber(credentials_path="/Users/xhu/Dev/jubu_backend/buju-stt-e073f0b8bca1.json")

#     # Record for 5 seconds and transcribe
#     transcription = transcriber.record_and_transcribe(5)
#     print(f"Transcription: {transcription}")
