"""
Speech-to-Text module for transcribing audio to text using various providers.
"""

from speech_services.speech_to_text.config_helper import (
    create_stt_config,
    initialize_stt_service,
)
from speech_services.speech_to_text.stt_factory import STTFactory
from speech_services.speech_to_text.stt_provider import STTProvider
from speech_services.speech_to_text.stt_service import STTService

__all__ = [
    "STTService",
    "STTFactory",
    "STTProvider",
    "create_stt_config",
    "initialize_stt_service",
]
