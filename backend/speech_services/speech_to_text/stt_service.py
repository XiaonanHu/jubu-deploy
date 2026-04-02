"""
Main Speech-to-Text service that provides a unified interface to different STT providers.
"""

from typing import Any, Dict, Optional

from speech_services.speech_to_text.stt_factory import STTFactory
from speech_services.speech_to_text.stt_provider import STTProvider


class STTService:
    """
    Service for handling Speech-to-Text operations using various providers.
    """

    def __init__(
        self,
        provider_name: str = "openai",
        provider_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the STT service with the specified provider.

        Args:
            provider_name: Name of the STT provider to use (default: openai)
            provider_config: Configuration for the STT provider
        """
        self.factory = STTFactory()
        self.provider_name = provider_name
        self.provider_config = provider_config or {}
        self.provider = self.factory.get_provider(provider_name, **self.provider_config)

    def change_provider(
        self, provider_name: str, provider_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Change the STT provider.

        Args:
            provider_name: Name of the new STT provider to use
            provider_config: Configuration for the new STT provider
        """
        self.provider_name = provider_name
        self.provider_config = provider_config or {}
        self.provider = self.factory.get_provider(provider_name, **self.provider_config)

    def transcribe_from_microphone(self, duration: Optional[int] = None) -> str:
        """
        Record audio from the microphone and transcribe it.

        Args:
            duration: Recording duration in seconds. If None, uses provider's default.

        Returns:
            Transcribed text
        """
        return self.provider.record_and_transcribe(duration)

    def transcribe_continuous(
        self, silence_threshold: float = 0.03, silence_duration: float = 1.0
    ) -> str:
        """
        Record audio continuously from the microphone until silence is detected,
        then transcribe it.

        Args:
            silence_threshold: Threshold for determining silence (0.0 to 1.0)
            silence_duration: Duration of silence in seconds before stopping

        Returns:
            Transcribed text
        """
        return self.provider.record_and_transcribe_continuous(
            silence_threshold, silence_duration
        )

    def transcribe_from_file(self, audio_file: str) -> str:
        """
        Transcribe an existing audio file.

        Args:
            audio_file: Path to the audio file

        Returns:
            Transcribed text
        """
        return self.provider.transcribe_audio(audio_file)

    def transcribe_from_bytes(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio data from bytes.

        Args:
            audio_bytes: The audio data in bytes.

        Returns:
            The transcribed text.
        """
        return self.provider.transcribe_from_bytes(audio_bytes)

    def get_available_providers(self) -> list:
        """
        Get a list of available STT providers.

        Returns:
            List of provider names
        """
        return self.factory.list_providers()
