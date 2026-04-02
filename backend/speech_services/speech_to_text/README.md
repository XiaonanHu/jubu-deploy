# Speech-to-Text Services

This module provides a unified interface for using different Speech-to-Text (STT) providers, including Google Cloud Speech-to-Text, OpenAI Whisper, and AssemblyAI.

## Architecture

The Speech-to-Text module follows a flexible, provider-based architecture:

```
┌─────────────┐     ┌───────────────┐     ┌───────────────┐
│ Application │────>│  STTService   │────>│  STTFactory   │
└─────────────┘     └───────────────┘     └───────┬───────┘
                           │                      │
                           │                      │ creates
                           │                      ▼
                           │              ┌───────────────┐
                           │              │  STTProvider  │
                           │              └───────┬───────┘
                           │                      │
                           │                      │ implements
                           │                      ▼
                           │             ┌────────────────────┐
                           └─────────────┤ Concrete Providers │
                                         └────────────────────┘
                                           │       │       │
                                           ▼       ▼       ▼
                                      ┌────────┬────────┬────────┐
                                      │ Google │ OpenAI │Assembly│
                                      │  STT   │  STT   │  STT   │
                                      └────────┴────────┴────────┘
```

### Key Components:

1. **`STTService`**: High-level service that provides a unified interface for transcription
2. **`STTFactory`**: Factory for creating and managing STT providers
3. **`STTProvider`**: Abstract base class defining the interface for all providers
4. **Concrete Providers**: Provider-specific implementations (Google, OpenAI, AssemblyAI)
5. **`config_helper`**: Helper functions for configuration and initialization

## Features

- Support for multiple STT providers
- Fixed-duration recording mode
- Continuous recording with automatic silence detection
- Simple and consistent API across providers
- Pluggable architecture for adding new providers

## Recording Modes

### Fixed-Duration Recording

Fixed-duration recording records audio for a specified number of seconds before transcribing:

```python
from speech_services.speech_to_text import initialize_stt_service

# Initialize with 5 seconds fixed duration recording
stt_service, success = initialize_stt_service("openai", duration=5)

if success:
    # Record for 5 seconds and transcribe
    transcription = stt_service.transcribe_from_microphone()
    print(f"Transcription: {transcription}")
```

### Continuous Recording with Silence Detection

Continuous recording listens until silence is detected for a specified duration:

```python
from speech_services.speech_to_text import initialize_stt_service

# Initialize with continuous mode
stt_service, success = initialize_stt_service("openai", continuous_mode=True)

if success:
    # Record until silence is detected, then transcribe
    transcription = stt_service.transcribe_continuous(
        silence_threshold=0.03,  # Lower is more sensitive
        silence_duration=1.0     # Seconds of silence to trigger end of recording
    )
    print(f"Transcription: {transcription}")
```

## File Transcription

In addition to microphone recording, you can transcribe existing audio files:

```python
from speech_services.speech_to_text import initialize_stt_service

stt_service, success = initialize_stt_service("openai")

if success:
    # Transcribe an existing audio file
    transcription = stt_service.transcribe_from_file("path/to/audio.wav")
    print(f"Transcription: {transcription}")
```

## Command-Line Usage

When using the KidsChat CLI, you can enable continuous recording with these options:

```bash
python -m jubu_chat.chat_cli --use-stt --continuous-stt --stt-provider openai
```

Additional options:
- `--silence-threshold`: Controls sensitivity (default: 0.03, lower is more sensitive)
- `--silence-duration`: Seconds of silence before stopping (default: 1.0)

## Supported Providers

- **Google Cloud Speech-to-Text** (`google`): High-quality transcription with support for multiple languages
- **OpenAI Whisper** (`openai`): State-of-the-art transcription model with high accuracy
- **AssemblyAI** (`assemblyai`): Cloud-based transcription with advanced features

## Provider-Specific Features

Each provider implementation includes:

- Audio recording capabilities
- Audio file transcription
- Provider-specific parameter handling
- Error handling and reporting
- Both fixed-duration and continuous recording modes

## Environment Variables

Each provider requires specific environment variables:

- Google: `GOOGLE_APPLICATION_CREDENTIALS` - Path to Google service account JSON file
- OpenAI: `OPENAI_API_KEY` - Your OpenAI API key
- AssemblyAI: `ASSEMBLYAI_API_KEY` - Your AssemblyAI API key

## Extending with New Providers

To add a new STT provider:

1. Create a new class that inherits from `STTProvider` in the providers directory
2. Implement all required methods: `record_audio`, `transcribe_audio`, `record_and_transcribe`, and `record_and_transcribe_continuous`
3. Register the provider with the factory:

```python
from speech_services.speech_to_text import STTFactory
from my_custom_provider import MyCustomProvider

factory = STTFactory()
factory.register_provider("custom", MyCustomProvider)
```

## Audio Processing Details

- Default sample rate: 16000 Hz
- Default audio channels: 1 (mono)
- Format: WAV (LINEAR16)
- Silence detection parameters are customizable
- Temporary files are automatically cleaned up after use 