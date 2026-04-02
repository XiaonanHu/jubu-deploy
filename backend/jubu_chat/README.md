# KidsChat CLI

A command-line interface for interacting with the KidsChat system. This CLI provides a simple way to test and demonstrate conversation capabilities with various configuration options.

## Basic Usage

### Text-Only Conversation

```bash
python -m jubu_chat.chat_cli
```

### Basic Voice Conversation (fixed duration)

```bash
python -m jubu_chat.chat_cli --use-stt --stt-provider openai
```

### Voice Conversation with Continuous Mode (silence detection)

```bash
python -m jubu_chat.chat_cli --use-stt --continuous-stt --stt-provider openai
```

### Fine-tuning Silence Detection

```bash
python -m jubu_chat.chat_cli --use-stt --continuous-stt --silence-threshold 0.02 --silence-duration 1.5
```

## Models

### Using OpenAI's GPT Models

```bash
python -m jubu_chat.chat_cli --model gpt-4
```

### Using Google's Gemini Models

```bash
python -m jubu_chat.chat_cli --model gemini-1.0-pro
```

### Using Anthropic's Claude Models

```bash
python -m jubu_chat.chat_cli --model claude-3-opus
```

## Interaction Types

### Chitchat Mode

```bash
python -m jubu_chat.chat_cli --interaction chitchat
```

### Educational Content

```bash
python -m jubu_chat.chat_cli --interaction edutainment
```

### Interactive Storytelling

```bash
python -m jubu_chat.chat_cli --interaction interactive_story
```

### Emotional Support

```bash
python -m jubu_chat.chat_cli --interaction emotional_support
```

### Pretend Play

```bash
python -m jubu_chat.chat_cli --interaction pretend_play
```

### Language Learning

```bash
python -m jubu_chat.chat_cli --interaction language_learning
```

### Math Learning

```bash
python -m jubu_chat.chat_cli --interaction math_learning
```

### Storytelling

```bash
python -m jubu_chat.chat_cli --interaction storytelling
```

### Tool Calling

```bash
python -m jubu_chat.chat_cli --interaction tool_calling
```

## Speech Services

### Speech-to-Text Providers

#### OpenAI STT

```bash
python -m jubu_chat.chat_cli --use-stt --stt-provider openai
```

#### Google STT

```bash
python -m jubu_chat.chat_cli --use-stt --stt-provider google
```

#### AssemblyAI STT

```bash
python -m jubu_chat.chat_cli --use-stt --stt-provider assemblyai
```

### Text-to-Speech Providers

#### ElevenLabs TTS

```bash
python -m jubu_chat.chat_cli --use-tts --tts-provider elevenlabs
```

#### Google TTS

```bash
python -m jubu_chat.chat_cli --use-tts --tts-provider google
```

#### OpenAI TTS

```bash
python -m jubu_chat.chat_cli --use-tts --tts-provider openai
```

### Full Voice Conversation (STT + TTS)

```bash
python -m jubu_chat.chat_cli --use-stt --continuous-stt --use-tts
```

## Child Profiles

### Using an Existing Child Profile (by ID)

```bash
python -m jubu_chat.chat_cli --child-id abc123
```

### Loading a Child Profile from a File

```bash
python -m jubu_chat.chat_cli --child-profile ./path/to/child_profile.json
```

### With Parental Settings

```bash
python -m jubu_chat.chat_cli --child-id abc123 --parental-settings ./path/to/parental_settings.json
```

## Advanced Options

### Debug Mode

```bash
python -m jubu_chat.chat_cli --debug
```

### Using an Experiment Configuration

```bash
python -m jubu_chat.chat_cli --experiment test_experiment_1
```

### Custom Configuration Directory

```bash
python -m jubu_chat.chat_cli --config-dir /path/to/custom/configs
```

## Combined Examples

### Full Setup with Continuous Voice, Child Profile, and Custom Model

```bash
python -m jubu_chat.chat_cli \
    --use-stt \
    --continuous-stt \
    --stt-provider openai \
    --use-tts \
    --tts-provider elevenlabs \
    --model gpt-4 \
    --interaction storytelling \
    --child-profile ./child_profile.json
```### Educational Setup with Speech Recognition for Classroom

```bash
python -m jubu_chat.chat_cli \
    --use-stt \
    --continuous-stt \
    --silence-threshold 0.04 \
    --silence-duration 1.2 \
    --use-tts \
    --interaction edutainment \
    --model gemini-1.0-pro
```

### Emotional Support Mode with Google Services

```bash
python -m jubu_chat.chat_cli \
    --use-stt \
    --stt-provider google \
    --use-tts \
    --tts-provider google \
    --interaction emotional_support
```

## Command Line Reference

| Option | Description |
|--------|-------------|
| `--config-dir` | Directory containing configuration files |
| `--model` | Override the model specified in the configuration |
| `--interaction` | Conversation mode/interaction type |
| `--experiment` | Experiment ID to use for configuration |
| `--debug` | Enable debug mode with additional logging |
| `--child-profile` | Path to JSON file containing child profile information |
| `--child-id` | ID of an existing child profile to use for the conversation |
| `--parental-settings` | Path to JSON file containing parental settings |
| `--use-stt` | Enable Speech-to-Text for input |
| `--stt-provider` | Speech-to-Text provider to use (openai, google, assemblyai) |
| `--stt-duration` | Default recording duration in seconds for STT (fixed duration mode only) |
| `--continuous-stt` | Enable continuous STT with automatic silence detection |
| `--silence-threshold` | Threshold for silence detection (0.0 to 1.0, lower is more sensitive) |
| `--silence-duration` | Duration of silence in seconds before stopping recording |
| `--use-tts` | Enable Text-to-Speech for output |
| `--tts-provider` | Text-to-Speech provider to use (elevenlabs, google, openai) |
| `--tts-voice` | Voice ID or name to use for TTS (provider-specific) |


