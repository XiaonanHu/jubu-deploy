"""
Text-to-Speech provider implementations.
"""

from speech_services.text_to_speech.providers.elevenlabs_tts import ElevenLabsSpeaker
from speech_services.text_to_speech.providers.google_tts import GoogleSpeaker
from speech_services.text_to_speech.providers.openai_tts import OpenAISpeaker

__all__ = ["ElevenLabsSpeaker", "GoogleSpeaker", "OpenAISpeaker"]
