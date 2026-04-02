import io
import os
import sys
import tempfile
import time
import wave
from typing import Any, Dict, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv
from openai import OpenAI

from speech_services.speech_to_text.stt_provider import STTProvider

# Load environment variables from .env file
load_dotenv()

"""
Other model options:
gpt-4o-mini-transcribe
gpt-4o-transcribe
"""


class OpenAITranscriber(STTProvider):
    """
    A class to handle microphone recording and transcription using OpenAI's Whisper model.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        language_code: str = "en",
    ):
        """
        Initialize the transcriber with OpenAI API credentials.

        Args:
            api_key: OpenAI API key. If None, will try to use OPENAI_API_KEY env variable.
            model: The model to use for transcription. The /v1/audio/transcriptions endpoint only supports "whisper-1".
            language_code: The language code for transcription (default: en)
        """
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.language_code = language_code

        # Default audio recording parameters
        self.sample_rate = 16000
        self.channels = 1
        self.record_seconds = 5  # Default recording duration

    def record_audio(self, duration: Optional[int] = None) -> str:
        """
        Record audio from the microphone.

        Args:
            duration: Recording duration in seconds. If None, uses default duration.

        Returns:
            Path to the temporary audio file
        """
        if duration is not None:
            self.record_seconds = duration

        print("Recording...")

        # Record audio
        recording = sd.rec(
            int(self.record_seconds * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
        )

        # Wait until recording is finished
        sd.wait()

        print("Recording finished.")

        # Create a temporary file to store the recording
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_filename = temp_file.name
        temp_file.close()

        # Save the recorded audio as a WAV file
        sf.write(temp_filename, recording, self.sample_rate)

        return temp_filename

    def record_audio_continuous(
        self, silence_threshold: float = 0.02, silence_duration: float = 1.0
    ) -> str:
        """
        Record audio continuously until silence is detected.

        Args:
            silence_threshold: Threshold for determining silence (0.0 to 1.0)
            silence_duration: Duration of silence in seconds before stopping

        Returns:
            Path to the temporary audio file
        """
        print(f"Recording... (speak now, will stop after detecting silence)")
        print(
            f"DEBUG: Using silence_threshold={silence_threshold}, silence_duration={silence_duration}s"
        )
        print("Volume meter: [----------] (higher values = louder)")

        # Parameters for recording
        chunk_duration = 0.1  # seconds per chunk
        chunk_size = int(self.sample_rate * chunk_duration)

        # Initialize variables
        audio_data = []
        silence_counter = 0
        has_speech = False
        recording_done = False  # Flag to track if recording is complete

        # For debugging - keep track of max volume
        max_volume = 0.001

        # Callback function to process audio chunks
        def audio_callback(indata, frames, time_info, status):
            nonlocal silence_counter, has_speech, max_volume, recording_done
            volume_norm = np.linalg.norm(indata) / np.sqrt(frames)

            # Track max volume for scaling the visual indicator
            max_volume = max(max_volume, volume_norm)

            # Add data to our audio buffer
            audio_data.append(indata.copy())

            # Check if this chunk is silence
            if volume_norm < silence_threshold:
                silence_counter += chunk_duration
                if has_speech and silence_counter >= silence_duration:
                    # If we've had speech before and now have enough silence, stop recording
                    recording_done = True
                    raise sd.CallbackStop
            else:
                silence_counter = 0
                has_speech = True

        # Start the recording stream
        stream = sd.InputStream(
            callback=audio_callback,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=chunk_size,
        )

        try:
            with stream:
                # Add a timeout as a failsafe (e.g., 30 seconds)
                max_record_time = 30  # seconds
                start_time = time.time()

                # For monitoring audio levels
                last_update_time = time.time()
                update_interval = 0.2  # seconds

                # Keep checking status until recording is done or timeout
                while not recording_done and time.time() - start_time < max_record_time:
                    # Visual feedback for audio levels
                    current_time = time.time()
                    if current_time - last_update_time >= update_interval:
                        # Get most recent audio
                        if audio_data:
                            recent_data = audio_data[-1]
                            volume_norm = np.linalg.norm(recent_data) / np.sqrt(
                                len(recent_data)
                            )

                            # Create visual indicator
                            bar_length = 10
                            # Scale relative to silence_threshold (make threshold the middle point)
                            relative_volume = min(
                                1.0, volume_norm / (silence_threshold * 2)
                            )
                            filled_length = int(bar_length * relative_volume)
                            bar = (
                                "|"
                                + "#" * filled_length
                                + "-" * (bar_length - filled_length)
                                + "|"
                            )

                            # Show speech/silence state
                            state = (
                                "SILENCE"
                                if volume_norm < silence_threshold
                                else "SPEECH"
                            )

                            # Clear the previous line and print the new one
                            sys.stdout.write("\r" + " " * 80)  # Clear line
                            sys.stdout.write(
                                f"\rVolume: {bar} {volume_norm:.4f} [{state}] (Threshold: {silence_threshold:.4f}, Silence: {silence_counter:.1f}s/{silence_duration:.1f}s)"
                            )
                            sys.stdout.flush()

                            last_update_time = current_time

                            # Check if we've had speech and now have enough silence to stop
                            if has_speech and silence_counter >= silence_duration:
                                recording_done = True
                                break

                    sd.sleep(10)  # Sleep for 10ms (more frequent updates)

                # Force stop the stream if we're done due to silence detection
                if recording_done:
                    # No need to do anything, we'll exit the context manager
                    pass
                elif time.time() - start_time >= max_record_time:
                    print("\nMaximum recording time reached.")

        except KeyboardInterrupt:
            print("\nRecording interrupted by user.")
        finally:
            # Clear the last line
            sys.stdout.write("\r" + " " * 80)
            sys.stdout.write("\r")
            sys.stdout.flush()

        print("\nRecording finished.")

        # Print some debugging stats
        if has_speech:
            print(f"DEBUG: Maximum volume detected: {max_volume:.4f}")
            print(
                f"DEBUG: Recording duration: {len(audio_data) * chunk_duration:.2f} seconds"
            )

        # If we didn't record any audio with speech, return empty string
        if not has_speech or not audio_data:
            print("No speech detected.")
            return ""

        # Concatenate all audio chunks
        audio_data = np.concatenate(audio_data, axis=0)

        # Create a temporary file to store the recording
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_filename = temp_file.name
        temp_file.close()

        # Save the recorded audio as a WAV file
        sf.write(temp_filename, audio_data, self.sample_rate)

        return temp_filename

    def transcribe_audio(self, audio_file: str) -> str:
        """
        Transcribe the audio file using OpenAI's Whisper model.

        Args:
            audio_file: Path to the audio file

        Returns:
            Transcribed text

        Raises:
            RuntimeError: If transcription fails
        """
        # If audio file is empty or doesn't exist, return empty string
        if (
            not audio_file
            or not os.path.exists(audio_file)
            or os.path.getsize(audio_file) == 0
        ):
            return ""

        try:
            with open(audio_file, "rb") as audio_data:
                response = self.client.audio.transcriptions.create(
                    model=self.model, file=audio_data, response_format="text"
                )

            return response if isinstance(response, str) else response.text
        except Exception as e:
            raise RuntimeError(f"Transcription failed: {str(e)}")

    def transcribe_from_bytes(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio data from bytes using OpenAI API.
        The audio_bytes are expected to be raw PCM data.
        """
        try:
            # Create a WAV file in memory
            wav_file = io.BytesIO()
            with wave.open(wav_file, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)  # 2 bytes for 16-bit audio
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_bytes)

            wav_file.seek(0)
            wav_file.name = "stream.wav"

            transcript = self.client.audio.transcriptions.create(
                model=self.model, file=wav_file, response_format="text"
            )
            return transcript if isinstance(transcript, str) else transcript.text
        except Exception as e:
            raise RuntimeError(f"Transcription from bytes failed: {str(e)}")

    def record_and_transcribe(self, duration: Optional[int] = None) -> str:
        """
        Record audio from the microphone and transcribe it.

        Args:
            duration: Recording duration in seconds. If None, uses default duration.

        Returns:
            Transcribed text
        """
        temp_filename = self.record_audio(duration)

        try:
            transcription = self.transcribe_audio(temp_filename)
            return transcription
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def record_and_transcribe_continuous(
        self, silence_threshold: float = 0.03, silence_duration: float = 1.0
    ) -> str:
        """
        Record audio continuously until silence is detected, then transcribe it.

        Args:
            silence_threshold: Threshold for determining silence (0.0 to 1.0)
            silence_duration: Duration of silence in seconds before stopping

        Returns:
            Transcribed text
        """
        temp_filename = self.record_audio_continuous(
            silence_threshold, silence_duration
        )

        try:
            # If no audio was recorded, return empty string
            if not temp_filename:
                return ""

            transcription = self.transcribe_audio(temp_filename)
            return transcription
        finally:
            # Clean up the temporary file
            if temp_filename and os.path.exists(temp_filename):
                os.unlink(temp_filename)


# Example usage
# if __name__ == "__main__":
#     # You can specify the API key directly
#     # transcriber = OpenAITranscriber(api_key="your-api-key")

#     # Or set the OPENAI_API_KEY environment variable
#     transcriber = OpenAITranscriber(api_key=os.getenv("OPENAI_API_KEY"))

#     # Record for 5 seconds and transcribe
#     transcription = transcriber.record_and_transcribe(5)
#     print(f"Transcription: {transcription}")
