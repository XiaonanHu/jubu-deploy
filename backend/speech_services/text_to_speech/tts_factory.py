"""
Factory for creating Text-to-Speech providers.
"""

from typing import Any, Dict, Optional, Type

from speech_services.text_to_speech.providers.elevenlabs_tts import ElevenLabsSpeaker
from speech_services.text_to_speech.providers.google_tts import GoogleSpeaker
from speech_services.text_to_speech.providers.openai_tts import OpenAISpeaker
from speech_services.text_to_speech.tts_provider import TTSProvider


class TTSFactory:
    """
    Factory for creating Text-to-Speech providers.
    """

    def __init__(self):
        """Initialize the TTS factory with available providers."""
        self._providers: Dict[str, Type[TTSProvider]] = {
            "elevenlabs": ElevenLabsSpeaker,
            "google": GoogleSpeaker,
            "openai": OpenAISpeaker,
        }

    def get_provider(self, provider_name: str, **kwargs) -> TTSProvider:
        """
        Get a Text-to-Speech provider by name.

        Args:
            provider_name: Name of the provider to get
            **kwargs: Additional arguments to pass to the provider constructor

        Returns:
            An instance of the requested TTS provider

        Raises:
            ValueError: If the provider is not found
        """
        provider_class = self._providers.get(provider_name.lower())
        if not provider_class:
            raise ValueError(
                f"TTS provider '{provider_name}' not found. Available providers: {', '.join(self._providers.keys())}"
            )

        return provider_class(**kwargs)

    def register_provider(self, name: str, provider_class: Type[TTSProvider]) -> None:
        """
        Register a new TTS provider.

        Args:
            name: Name to register the provider under
            provider_class: The provider class to register
        """
        self._providers[name.lower()] = provider_class

    def list_providers(self) -> list:
        """
        List all available TTS providers.

        Returns:
            List of provider names
        """
        return list(self._providers.keys())
