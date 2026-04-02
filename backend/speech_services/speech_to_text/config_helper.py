"""
Helper functions for configuring Speech-to-Text services.
"""

import os
from typing import Any, Dict, Optional, Tuple

from infrastructure.logging import get_logger
from speech_services.speech_to_text.stt_service import STTService

logger = get_logger(__name__)


def create_stt_config(provider_name: str) -> Dict[str, Any]:
    """
    Create a configuration dictionary for the specified STT provider
    based on environment variables.

    Args:
        provider_name: Name of the STT provider

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

    elif provider_name == "assemblyai":
        # Try to get API key from environment
        api_key = os.getenv("ASSEMBLYAI_API_KEY")
        if api_key:
            config["api_key"] = api_key

    return config


def initialize_stt_service(
    provider_name: str,
    duration: Optional[int] = None,
    continuous_mode: bool = False,
    language_code: str = "en",
) -> Tuple[Optional[STTService], bool]:
    """
    Initialize an STT service with the specified provider.

    Args:
        provider_name: Name of the STT provider to use
        duration: Default recording duration in seconds for fixed-duration mode
        continuous_mode: Whether to use continuous recording with silence detection
        language_code: The language code for transcription (default: en)

    Returns:
        tuple: (STT service instance, success flag)
    """

    try:
        # Create provider configuration
        provider_config = create_stt_config(provider_name)

        # Add language_code to config if the provider is openai
        if provider_name == "openai":
            provider_config["language_code"] = language_code

        # Initialize STT service
        stt_service = STTService(
            provider_name=provider_name, provider_config=provider_config
        )

        # Set default duration if provided and not in continuous mode
        if (
            not continuous_mode
            and duration is not None
            and hasattr(stt_service.provider, "record_seconds")
        ):
            stt_service.provider.record_seconds = duration

        # Log configuration
        if continuous_mode:
            logger.info(
                f"STT service initialized in continuous mode with provider: {provider_name}"
            )
        else:
            logger.info(
                f"STT service initialized with provider: {provider_name}, duration: {duration}s"
            )

        return stt_service, True

    except Exception as e:
        logger.error(f"Failed to initialize STT service: {e}")
        return None, False
