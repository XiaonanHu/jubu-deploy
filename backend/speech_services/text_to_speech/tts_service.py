"""
Main Text-to-Speech service that provides a unified interface to different TTS providers.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, cast

from speech_services.text_to_speech.tts_factory import TTSFactory
from speech_services.text_to_speech.tts_provider import TTSProvider

logger = logging.getLogger(__name__)


class TTSService:
    """
    Service for handling Text-to-Speech operations using various providers.
    """

    def __init__(
        self,
        provider_name: str = "openai",
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the TTS service with the specified provider.

        Args:
            provider_name: Name of the TTS provider to use (default: openai)
            provider_config: Configuration for the TTS provider
        """
        self.factory = TTSFactory()
        self.provider_name = provider_name
        self.provider_config = provider_config or {}
        self.provider = self.factory.get_provider(provider_name, **self.provider_config)

    def change_provider(
        self, provider_name: str, provider_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Change the TTS provider.

        Args:
            provider_name: Name of the new TTS provider to use
            provider_config: Configuration for the new TTS provider
        """
        self.provider_name = provider_name
        self.provider_config = provider_config or {}
        self.provider = self.factory.get_provider(provider_name, **self.provider_config)

    def speak_text(self, text: str, **kwargs) -> None:
        """
        Convert text to speech and play it.

        Args:
            text: The text to speak
            **kwargs: Additional provider-specific parameters
        """
        return self.provider.speak(text, **kwargs)

    def generate_audio(self, text: str, **kwargs) -> bytes:
        """
        Convert text to speech and return the audio data.

        Args:
            text: The text to convert to speech
            **kwargs: Additional provider-specific parameters

        Returns:
            Audio data as bytes
        """
        return self.provider.text_to_speech(text, **kwargs)

    def save_audio(self, text: str, file_path: str, **kwargs) -> str:
        """
        Convert text to speech and save it to a file.

        Args:
            text: The text to convert to speech
            file_path: Path to save the audio file
            **kwargs: Additional provider-specific parameters

        Returns:
            Path to the saved audio file
        """
        audio_data = self.provider.text_to_speech(text, **kwargs)
        return self.provider.save_to_file(audio_data, file_path)

    def list_available_voices(self) -> List[Dict[str, Any]]:
        """
        Get a list of available voices from the current provider.

        Returns:
            List of voice information dictionaries
        """
        return self.provider.list_available_voices()

    def get_available_providers(self) -> list:
        """
        Get a list of available TTS providers.

        Returns:
            List of provider names
        """
        return self.factory.list_providers()

    async def stream_audio(
        self, text_stream: AsyncIterator[str], **kwargs
    ) -> AsyncIterator[bytes]:
        """
        Stream audio chunks for a stream of text chunks. Falls back to batch synthesis if streaming is unavailable.
        """
        provider: TTSProvider = self.provider
        started_at = time.monotonic()

        # Try provider-native streaming first
        try:
            first = True
            stream_result = provider.stream_text_to_speech(text_stream, **kwargs)
            if asyncio.iscoroutine(stream_result):
                iterator: AsyncIterator[bytes] = cast(
                    AsyncIterator[bytes], await stream_result
                )
            else:
                iterator = cast(AsyncIterator[bytes], stream_result)
            async for chunk in iterator:
                if first:
                    ttfa = time.monotonic() - started_at
                    logger.info(
                        f"LATENCY-b| tts.native_ttfa_generated | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int(ttfa*1000)} | provider={self.provider_name}"
                    )
                    first = False
                yield chunk
            total = time.monotonic() - started_at
            logger.info(
                f"LATENCY-b| tts.native_stream_complete | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int(total*1000)} | provider={self.provider_name}"
            )
            return
        except NotImplementedError:
            pass

        # Fallback: buffer all text and synthesize once
        buffered_text_parts: List[str] = []
        async for part in text_stream:
            if part:
                buffered_text_parts.append(part)
        full_text = "".join(buffered_text_parts)
        if not full_text:
            return
        loop = asyncio.get_event_loop()
        synth_start = time.monotonic()
        audio_bytes = await loop.run_in_executor(
            None, lambda: provider.text_to_speech(full_text, **kwargs)
        )
        dt = time.monotonic() - synth_start
        logger.info(
            f"LATENCY-b| tts.fallback_batch | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int(dt*1000)} | provider={self.provider_name} | bytes={len(audio_bytes) if audio_bytes else 0}"
        )
        if audio_bytes:
            yield audio_bytes
