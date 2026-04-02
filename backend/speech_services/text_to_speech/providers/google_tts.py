import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from google.cloud import texttospeech
from google.oauth2 import service_account

from speech_services.text_to_speech.tts_provider import TTSProvider


class GoogleSpeaker(TTSProvider):
    """
    A class to handle text-to-speech conversion using Google Cloud Text-to-Speech API.
    """

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        language_code: str = "en-US",
        voice_name: str = "en-US-Standard-C",
    ):
        """
        Initialize the speaker with Google Cloud Text-to-Speech credentials.

        Args:
            credentials_path: Path to the Google Cloud service account JSON file.
                             If None, will try to use GOOGLE_APPLICATION_CREDENTIALS env variable.
            language_code: The language code for speech synthesis (default: en-US)
            voice_name: The voice name to use (default: en-US-Standard-C)
        """
        if credentials_path:
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_path
            )
            self.client = texttospeech.TextToSpeechClient(credentials=self.credentials)
        else:
            # Will use GOOGLE_APPLICATION_CREDENTIALS environment variable
            self.client = texttospeech.TextToSpeechClient()

        self.language_code = language_code
        self.voice_name = voice_name

    def list_available_voices(self) -> List[Dict[str, Any]]:
        """
        Get a list of available voices from Google Cloud Text-to-Speech.

        Returns:
            List of voice information dictionaries
        """
        try:
            response = self.client.list_voices()
            voices = []

            for voice in response.voices:
                voice_info = {
                    "name": voice.name,
                    "language_codes": list(voice.language_codes),
                    "ssml_gender": texttospeech.SsmlVoiceGender(voice.ssml_gender).name,
                    "natural_sample_rate_hertz": voice.natural_sample_rate_hertz,
                }
                voices.append(voice_info)

            return voices
        except Exception as e:
            print(f"Failed to list voices: {e}")
            return []

    def text_to_speech(
        self,
        text: str,
        voice_name: Optional[str] = None,
        language_code: Optional[str] = None,
        ssml: bool = False,
    ) -> bytes:
        """
        Convert text to speech using Google Cloud Text-to-Speech API.

        Args:
            text: The text to convert to speech
            voice_name: The voice name to use (overrides the default)
            language_code: The language code to use (overrides the default)
            ssml: Whether the input text is SSML

        Returns:
            Audio data as bytes

        Raises:
            RuntimeError: If text-to-speech conversion fails
        """
        try:
            # Set up the input
            if ssml:
                synthesis_input = texttospeech.SynthesisInput(ssml=text)
            else:
                synthesis_input = texttospeech.SynthesisInput(text=text)

            # Build the voice request
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code or self.language_code,
                name=voice_name or self.voice_name,
            )

            # Select the audio file type
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )

            # Perform the text-to-speech request
            response = self.client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            return response.audio_content
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
        voice_name: Optional[str] = None,
        language_code: Optional[str] = None,
        ssml: bool = False,
    ) -> None:
        """
        Convert text to speech and play it.

        Args:
            text: The text to speak
            voice_name: The voice name to use (overrides the default)
            language_code: The language code to use (overrides the default)
            ssml: Whether the input text is SSML
        """
        audio_data = self.text_to_speech(text, voice_name, language_code, ssml)

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
