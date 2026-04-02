import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from speech_services.text_to_speech.tts_provider import TTSProvider

# Load environment variables from .env file
load_dotenv()


class OpenAISpeaker(TTSProvider):
    """
    A class to handle text-to-speech conversion using OpenAI's TTS API.
    """

    def __init__(
        self, api_key: Optional[str] = None, model: str = "tts-1", voice: str = "alloy"
    ):
        """
        Initialize the speaker with OpenAI API credentials.

        Args:
            api_key: OpenAI API key. If None, will try to use OPENAI_API_KEY env variable.
            model: The model to use for speech synthesis (default: tts-1)
            voice: The voice to use (default: alloy)
        """
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

        # Available voices in OpenAI TTS
        self._available_voices = [
            {
                "id": "alloy",
                "name": "Alloy",
                "description": "Versatile, balanced voice",
            },
            {"id": "echo", "name": "Echo", "description": "Soft, warm voice"},
            {
                "id": "fable",
                "name": "Fable",
                "description": "Narrative, soothing voice",
            },
            {"id": "onyx", "name": "Onyx", "description": "Deep, authoritative voice"},
            {"id": "nova", "name": "Nova", "description": "Energetic, upbeat voice"},
            {"id": "shimmer", "name": "Shimmer", "description": "Clear, bright voice"},
        ]

    def list_available_voices(self) -> List[Dict[str, Any]]:
        """
        Get a list of available voices from OpenAI TTS.

        Returns:
            List of voice information dictionaries
        """
        return self._available_voices

    def text_to_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: float = 1.0,
    ) -> bytes:
        """
        Convert text to speech using OpenAI's TTS API.

        Args:
            text: The text to convert to speech
            voice: The voice to use (overrides the default)
            model: The model to use (overrides the default)
            speed: Speech speed multiplier (0.25-4.0)

        Returns:
            Audio data as bytes

        Raises:
            RuntimeError: If text-to-speech conversion fails
        """
        try:
            response = self.client.audio.speech.create(
                model=model or self.model,
                voice=voice or self.voice,
                input=text,
                speed=speed,
            )

            # Get the audio content
            audio_data = response.content

            return audio_data
        except Exception as e:
            raise RuntimeError(f"Text-to-speech conversion failed: {str(e)}")

    def save_to_file(self, audio_data: bytes, file_path: str) -> str:
        """
        Save audio data to a file.

        Args:
            audio_data: The audio data as bytes
            file_path: The path to save the audio file

        Returns:
            The path to the saved file
        """
        with open(file_path, "wb") as f:
            f.write(audio_data)
        return file_path

    def speak(
        self,
        text: str,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: float = 1.0,
    ) -> None:
        """
        Convert text to speech and play it.

        Args:
            text: The text to speak
            voice: The voice to use (overrides the default)
            model: The model to use (overrides the default)
            speed: Speech speed multiplier (0.25-4.0)
        """
        audio_data = self.text_to_speech(text, voice, model, speed)

        # Create a temporary file to store the audio
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_filename = temp_file.name
        temp_file.close()

        try:
            # Save the audio data to the temporary file
            self.save_to_file(audio_data, temp_filename)

        finally:
            # Clean up the temporary file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)
