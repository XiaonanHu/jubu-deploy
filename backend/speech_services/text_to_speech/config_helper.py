"""
Helper functions for configuring Text-to-Speech services.
"""

import os
from typing import Any, Dict, Optional

from infrastructure.logging import get_logger
from speech_services.text_to_speech.tts_service import TTSService

logger = get_logger(__name__)


def create_tts_config(provider_name: str) -> Dict[str, Any]:
    """
    Create a configuration dictionary for the specified TTS provider
    based on environment variables.

    Args:
        provider_name: Name of the TTS provider

    Returns:
        Configuration dictionary for the provider
    """
    config = {}

    if provider_name == "google":
        # Try to get credentials path from environment
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if credentials_path:
            config["credentials_path"] = credentials_path

    elif provider_name == "openai":
        # Try to get API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            config["api_key"] = api_key

    elif provider_name == "elevenlabs":
        # Try to get API key from environment
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if api_key:
            config["api_key"] = api_key

    return config


def initialize_tts_service(provider_name: str, voice: Optional[str] = None):
    """
    Initialize a TTS service with the specified provider.

    Args:
        provider_name: Name of the TTS provider to use
        voice: Voice ID or name to use (provider-specific)

    Returns:
        tuple: (TTS service instance, success flag)
    """

    try:
        # Create provider configuration
        provider_config = create_tts_config(provider_name)

        # Add voice to config if provided
        if voice is not None:
            if provider_name == "elevenlabs":
                provider_config["voice_id"] = voice
            elif provider_name == "google":
                provider_config["voice_name"] = voice
            elif provider_name == "openai":
                provider_config["voice"] = voice

        # Initialize TTS service
        tts_service = TTSService(
            provider_name=provider_name, provider_config=provider_config
        )

        return tts_service, True

    except Exception as e:
        logger.error(f"Failed to initialize TTS service: {e}")
        return None, False
