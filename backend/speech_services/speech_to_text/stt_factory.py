"""
Factory for creating Speech-to-Text providers.
"""

from typing import Any, Dict, Optional, Type

from speech_services.speech_to_text.providers.assembly_stt import AssemblyAITranscriber
from speech_services.speech_to_text.providers.google_stt import GoogleTranscriber
from speech_services.speech_to_text.providers.openai_stt import OpenAITranscriber
from speech_services.speech_to_text.stt_provider import STTProvider


class STTFactory:
    """
    Factory for creating Speech-to-Text providers.
    """

    def __init__(self):
        """Initialize the STT factory with available providers."""
        self._providers: Dict[str, Type[STTProvider]] = {
            "assemblyai": AssemblyAITranscriber,
            "google": GoogleTranscriber,
            "openai": OpenAITranscriber,
        }

    def get_provider(self, provider_name: str, **kwargs) -> STTProvider:
        """
        Get a Speech-to-Text provider by name.

        Args:
            provider_name: Name of the provider to get
            **kwargs: Additional arguments to pass to the provider constructor

        Returns:
            An instance of the requested STT provider

        Raises:
            ValueError: If the provider is not found
        """
        provider_class = self._providers.get(provider_name.lower())
        if not provider_class:
            raise ValueError(
                f"STT provider '{provider_name}' not found. Available providers: {', '.join(self._providers.keys())}"
            )

        return provider_class(**kwargs)

    def register_provider(self, name: str, provider_class: Type[STTProvider]) -> None:
        """
        Register a new STT provider.

        Args:
            name: Name to register the provider under
            provider_class: The provider class to register
        """
        self._providers[name.lower()] = provider_class

    def list_providers(self) -> list:
        """
        List all available STT providers.

        Returns:
            List of provider names
        """
        return list(self._providers.keys())
