"""
Base interface for Speech-to-Text providers.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional


class STTProvider(ABC):
    """
    Abstract base class for all Speech-to-Text providers.
    Defines the common interface that all STT providers must implement.
    """

    @abstractmethod
    def record_audio(self, duration: Optional[int] = None) -> str:
        """
        Record audio from the microphone.

        Args:
            duration: Recording duration in seconds. If None, uses default duration.

        Returns:
            Path to the temporary audio file
        """
        pass

    @abstractmethod
    def transcribe_audio(self, audio_file: str) -> str:
        """
        Transcribe the audio file.

        Args:
            audio_file: Path to the audio file

        Returns:
            Transcribed text
        """
        pass

    @abstractmethod
    def record_and_transcribe(self, duration: Optional[int] = None) -> str:
        """
        Record audio from the microphone and transcribe it.

        Args:
            duration: Recording duration in seconds. If None, uses default duration.

        Returns:
            Transcribed text
        """
        pass

    @abstractmethod
    def record_and_transcribe_continuous(
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
        pass

    @abstractmethod
    def transcribe_from_bytes(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio data from bytes.

        Args:
            audio_bytes: The audio data in bytes.

        Returns:
            The transcribed text.
        """
        pass

    @abstractmethod
    async def stream_transcribe(
        self, audio_chunk_iterator: AsyncGenerator[bytes, None]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Transcribe an audio stream in real-time.

        Args:
            audio_chunk_iterator: An async generator that yields audio chunks in bytes.

        Yields:
            A dictionary representing the transcription result, which could be
            interim or final. e.g., {"text": "hello world", "is_final": True}
        """
        # This is an abstract method, so it must be an async generator.
        # The `yield` statement makes it a generator. An empty dict is a placeholder.
        yield {}
