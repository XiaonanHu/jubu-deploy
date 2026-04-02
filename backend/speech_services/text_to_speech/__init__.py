"""
Text-to-Speech module for converting text to speech using various providers.
"""

from speech_services.text_to_speech.config_helper import (
    create_tts_config,
    initialize_tts_service,
)
from speech_services.text_to_speech.tts_factory import TTSFactory
from speech_services.text_to_speech.tts_provider import TTSProvider
from speech_services.text_to_speech.tts_service import TTSService

__all__ = [
    "TTSService",
    "TTSFactory",
    "TTSProvider",
    "create_tts_config",
    "initialize_tts_service",
]
