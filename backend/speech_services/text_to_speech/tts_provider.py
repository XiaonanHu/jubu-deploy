"""
Base interface for Text-to-Speech providers.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional, Union


class TTSProvider(ABC):
    """
    Abstract base class for all Text-to-Speech providers.
    Defines the common interface that all TTS providers must implement.
    """

    @abstractmethod
    def text_to_speech(self, text: str, **kwargs) -> bytes:
        """
        Convert text to speech.

        Args:
            text: The text to convert to speech
            **kwargs: Additional provider-specific parameters

        Returns:
            Audio data as bytes
        """
        pass

    @abstractmethod
    def save_to_file(self, audio_data: bytes, file_path: str) -> str:
        """
        Save audio data to a file.

        Args:
            audio_data: The audio data as bytes
            file_path: The path to save the audio file

        Returns:
            The path to the saved file
        """
        pass

    @abstractmethod
    def speak(self, text: str, **kwargs) -> None:
        """
        Convert text to speech and play it.

        Args:
            text: The text to speak
            **kwargs: Additional provider-specific parameters
        """
        pass

    def list_available_voices(self) -> List[Dict[str, Any]]:
        """
        Get a list of available voices from the provider.

        Returns:
            List of voice information dictionaries
        """
        return []

    async def stream_text_to_speech(
        self, text_stream: AsyncIterator[str], **kwargs
    ) -> AsyncIterator[bytes]:
        """
        Optional streaming interface: convert a stream of text chunks into a stream of audio chunks.

        Providers may override this to support low-latency streaming synthesis.
        The default implementation raises NotImplementedError.
        """
        raise NotImplementedError("Streaming TTS is not implemented for this provider.")
