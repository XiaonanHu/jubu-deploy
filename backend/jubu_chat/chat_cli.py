"""
Command-line interface for KidsChat.

This module provides a simple CLI for interacting with the KidsChat system,
allowing for quick testing and demonstration of the conversation capabilities.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from infrastructure.logging import get_logger
from jubu_chat.chat.core.config_manager import BaseConfig, ConfigManager
from jubu_chat.chat.core.conversation_manager import ConversationManager
from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory
from jubu_chat.chat.domain.enums import ConversationState
from jubu_chat.chat.models.gemini_model import GeminiModel
from jubu_chat.chat.models.model_factory import ModelFactory
from speech_services.speech_to_text import initialize_stt_service
from speech_services.text_to_speech import initialize_tts_service

logger = get_logger(__name__)
load_dotenv()


def setup_argparse():
    """Set up command-line argument parsing."""
    parser = argparse.ArgumentParser(description="KidsChat CLI")
    parser.add_argument(
        "--config-dir",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "configs"),
        help="Directory containing configuration files",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Override the model specified in the configuration",
    )
    parser.add_argument(
        "--interaction",
        type=str,
        choices=[
            "chitchat",
            "edutainment",
            "emotional_support",
            "interactive_story",
            "pretend_play",
            "language_learning",
            "math_learning",
            "storytelling",
            "tool_calling",
        ],
        help="Conversation mode/interaction type",
    )
    parser.add_argument(
        "--experiment",
        type=str,
        help="Experiment ID to use for configuration",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode with additional logging",
    )
    parser.add_argument(
        "--child-profile",
        type=str,
        help="Path to JSON file containing child profile information",
    )
    parser.add_argument(
        "--child-id",
        type=str,
        help="ID of an existing child profile to use for the conversation",
    )
    parser.add_argument(
        "--parental-settings",
        type=str,
        help="Path to JSON file containing parental settings",
    )
    parser.add_argument(
        "--use-stt",
        action="store_true",
        help="Enable Speech-to-Text for input",
    )
    parser.add_argument(
        "--stt-provider",
        type=str,
        default="openai",
        choices=["openai", "google", "assemblyai"],
        help="Speech-to-Text provider to use",
    )
    parser.add_argument(
        "--stt-duration",
        type=int,
        default=5,
        help="Default recording duration in seconds for STT (fixed duration mode only)",
    )
    parser.add_argument(
        "--continuous-stt",
        action="store_true",
        help="Enable continuous STT with automatic silence detection",
    )
    parser.add_argument(
        "--silence-threshold",
        type=float,
        default=0.005,
        help="Threshold for silence detection (0.0 to 1.0, lower is more sensitive)",
    )
    parser.add_argument(
        "--silence-duration",
        type=float,
        default=1.0,
        help="Duration of silence in seconds before stopping recording",
    )
    parser.add_argument(
        "--use-tts",
        action="store_true",
        help="Enable Text-to-Speech for output",
    )
    parser.add_argument(
        "--tts-provider",
        type=str,
        default="elevenlabs",
        choices=["elevenlabs", "google", "openai"],
        help="Text-to-Speech provider to use",
    )
    parser.add_argument(
        "--tts-voice",
        type=str,
        help="Voice ID or name to use for TTS (provider-specific)",
    )
    return parser


def main():
    """Run the KidsChat CLI."""
    parser = setup_argparse()
    args = parser.parse_args()

    # Set up configuration
    config_manager = ConfigManager(BaseConfig, config_dir=args.config_dir)

    # Create runtime overrides based on command-line arguments
    runtime_overrides = {}
    if args.model:
        runtime_overrides["conversation"] = {"model": args.model}
    # interaction_type argument is accepted but ignored — always uses chitchat (unified prompt)
    if args.interaction and args.interaction != "chitchat":
        logger.warning(
            f"Interaction type '{args.interaction}' is deprecated. Using unified chitchat prompt."
        )
    if args.debug:
        runtime_overrides["system"] = {"log_level": "DEBUG"}

    # Create configuration
    try:
        config = config_manager.create_all_configs(
            experiment_id=args.experiment, runtime_overrides=runtime_overrides
        )
    except Exception as e:
        logger.error(f"Failed to create configuration: {e}")
        print(f"Error: Failed to create configuration: {e}")
        sys.exit(1)

    # Initialize model factory
    try:
        model_factory = ModelFactory(config_manager)
        model_factory.register_provider("google", GeminiModel)
    except Exception as e:
        logger.error(f"Failed to initialize model factory: {e}")
        print(f"Error: Failed to initialize model factory: {e}")
        sys.exit(1)

    # Load child profile if provided
    child_profile = None
    if args.child_id:
        try:
            # Load profile from database
            profile_datastore = DatastoreFactory.create_profile_datastore()
            profile = profile_datastore.get(args.child_id)
            if profile:
                # Convert Pydantic model to dict to work with ConversationManager
                # Use model_dump() for Pydantic v2 instead of dict()
                if hasattr(profile, "model_dump"):
                    child_profile = profile.model_dump()
                    logger.info(f"Using model_dump() for profile conversion")
                else:
                    child_profile = profile.dict()
                    logger.info(f"Using dict() for profile conversion")

                logger.info(
                    f"Loaded child profile from database: {profile.name}, age: {profile.age}"
                )
                logger.info(f"Child profile keys: {list(child_profile.keys())}")
                logger.info(
                    f"Child profile has ID: {child_profile.get('id') is not None}"
                )
            else:
                logger.error(f"Child profile with ID {args.child_id} not found")
                print(f"Error: Child profile with ID {args.child_id} not found")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to load child profile from database: {e}")
            print(f"Error: Failed to load child profile from database: {e}")
            sys.exit(1)
    elif args.child_profile:
        try:
            with open(args.child_profile, "r") as f:
                child_profile = json.load(f)
            logger.info(f"Loaded child profile from {args.child_profile}")
        except Exception as e:
            logger.error(f"Failed to load child profile: {e}")
            print(f"Warning: Failed to load child profile: {e}")

    # Load parental settings if provided
    parental_settings = None
    if args.parental_settings:
        try:
            with open(args.parental_settings, "r") as f:
                parental_settings = json.load(f)
            logger.info(f"Loaded parental settings from {args.parental_settings}")
        except Exception as e:
            logger.error(f"Failed to load parental settings: {e}")
            print(f"Warning: Failed to load parental settings: {e}")

    # Initialize STT service if enabled
    stt_service = None
    if args.use_stt:
        stt_service, success = initialize_stt_service(
            args.stt_provider, args.stt_duration, continuous_mode=args.continuous_stt
        )
        if success:
            if args.continuous_stt:
                print(
                    f"Speech-to-Text enabled using {args.stt_provider} provider with continuous mode"
                )
                print(
                    f"Silence threshold: {args.silence_threshold}, silence duration: {args.silence_duration}s"
                )
            else:
                print(
                    f"Speech-to-Text enabled using {args.stt_provider} provider with {args.stt_duration}s fixed duration"
                )
        else:
            print(f"Warning: Failed to initialize STT service")
            print("Continuing without Speech-to-Text capability")
            args.use_stt = False

    # Initialize TTS service if enabled
    tts_service = None
    if args.use_tts:
        tts_service, success = initialize_tts_service(args.tts_provider, args.tts_voice)
        if success:
            print(f"Text-to-Speech enabled using {args.tts_provider} provider")
        else:
            print(f"Warning: Failed to initialize TTS service")
            print("Continuing without Text-to-Speech capability")
            args.use_tts = False

    # Create conversation manager
    try:
        # For child profiles, either pass the full profile dictionary or just the ID
        if args.child_id:
            logger.info(f"Using child ID: {args.child_id}")
            conversation_manager = ConversationManager(
                config=config,
                child_id=args.child_id,  # Pass the ID directly
                parental_settings=parental_settings,
                model_factory=model_factory,
            )
        else:
            conversation_manager = ConversationManager(
                config=config,
                child_profile=child_profile,
                parental_settings=parental_settings,
                model_factory=model_factory,
            )
    except Exception as e:
        logger.error(f"Failed to create conversation manager: {e}")
        print(f"Error: Failed to create conversation manager: {e}")
        sys.exit(1)

    print(f"\nWelcome to KidsChat CLI!")
    print(f"Using model: {config.conversation.model}")
    print(f"Interaction: chitchat (unified prompt)")
    if child_profile:
        print(
            f"Child profile: {child_profile.get('name', 'Unknown')}, Age: {child_profile.get('age', 'Unknown')}"
        )
    print(f"Type 'exit' or 'quit' to end the conversation.")
    if args.use_stt:
        print(f"For your first message, you can choose your preferred input method:")
        print(f"- Press Enter or type 'voice' to use voice input for all turns")
        print(f"- Type any other text to use text input for all turns")
        print(f"This choice will be remembered for the entire conversation.")
    print()

    # Main conversation loop
    # Keep track of whether the user wants to use text input
    use_text_input = False
    first_turn = True

    while conversation_manager.state != ConversationState.ENDED:
        # Get user input
        try:
            if args.use_stt and not use_text_input:
                # Ask for input type only for the first turn
                if first_turn:
                    text_input = input(
                        "You (type 'voice' or press Enter for voice input, or type to use text): "
                    )
                    if text_input and text_input.lower() != "voice":
                        # User wants to use text input for all turns
                        user_message = text_input
                        use_text_input = True
                        logger.info(
                            "User chose text input for the first turn, will use text for all turns"
                        )
                    else:
                        # Start voice recording
                        logger.info(
                            "User chose voice input for the first turn, will use voice for all turns"
                        )
                        if args.continuous_stt:
                            print("Listening until silence is detected...")
                            print(
                                f"Silence threshold: {args.silence_threshold}, silence duration: {args.silence_duration}s"
                            )
                            user_message = stt_service.transcribe_continuous(
                                silence_threshold=args.silence_threshold,
                                silence_duration=args.silence_duration,
                            )
                        else:
                            print(f"Listening for {args.stt_duration} seconds...")
                            user_message = stt_service.transcribe_from_microphone(
                                args.stt_duration
                            )

                        # If no transcription was returned or it's empty, allow manual text input
                        if not user_message:
                            print("No speech detected. Type your message instead:")
                            user_message = input("You: ")
                        else:
                            print(f"You said: {user_message}")
                else:
                    # Auto-recording for subsequent turns (user chose voice on first turn)
                    print("\nYour turn (recording automatically)...")

                    if args.continuous_stt:
                        print("Listening until silence is detected...")
                        print(
                            f"Silence threshold: {args.silence_threshold}, silence duration: {args.silence_duration}s"
                        )
                        user_message = stt_service.transcribe_continuous(
                            silence_threshold=args.silence_threshold,
                            silence_duration=args.silence_duration,
                        )
                    else:
                        print(f"Listening for {args.stt_duration} seconds...")
                        user_message = stt_service.transcribe_from_microphone(
                            args.stt_duration
                        )

                    # If no transcription was returned or it's empty, allow manual text input
                    if not user_message:
                        print("No speech detected. Type your message instead:")
                        user_message = input("You: ")
                    else:
                        print(f"You said: {user_message}")
            else:
                # Either STT is disabled or user chose to use text input
                user_message = input("You: ")

            # First turn is complete
            first_turn = False
        except (KeyboardInterrupt, EOFError):
            print("\nEnding conversation. Goodbye!")
            conversation_manager.end_conversation()
            break

        # Check for exit command
        if user_message.lower() in ["exit", "quit"]:
            print("\nEnding conversation. Goodbye!")
            conversation_manager.end_conversation()
            break

        # Process the message
        try:
            response_dict = conversation_manager.process_turn(user_message)
            interaction_type = response_dict.get("interaction_type")
            response = response_dict.get("system_response")
            print(f"\nKidsChat: {response}\n")

            # Use TTS to speak the response if enabled
            if args.use_tts:
                try:
                    tts_service.speak_text(response)
                except Exception as e:
                    logger.error(f"TTS error: {e}")
                    print(f"Error speaking response: {e}")

            if interaction_type:
                print(f"[Interaction type: {interaction_type}]")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            print("\nSorry, I encountered an error. Let's try again.\n")

    # End the conversation properly
    try:
        if conversation_manager.state != ConversationState.ENDED:
            logger.info("Explicitly ending conversation before exit")
            conversation_manager.end_conversation()

        # Log important conversation details
        child_id = None
        parent_id = None

        if hasattr(conversation_manager.conversation_context, "child_profile"):
            child_id = conversation_manager.conversation_context.child_profile.id
            parent_id = getattr(
                conversation_manager.conversation_context.child_profile,
                "parent_id",
                None,
            )

        logger.info(
            f"Conversation ended with ID: {conversation_manager.conversation_id}"
        )
        logger.info(f"Child ID: {child_id}, Parent ID: {parent_id}")
        logger.info(f"Conversation state: {conversation_manager.state.value}")
    except Exception as e:
        logger.error(f"Error ending conversation: {e}")

    # Print conversation summary
    try:
        summary = conversation_manager.get_conversation_summary()
        print("\nConversation Summary:")
        print(f"- Conversation ID: {summary['conversation_id']}")
        print(f"- Turns: {summary['turns']}")
        print(f"- Duration: {summary['duration_seconds']:.1f} seconds")
        print(f"- Facts extracted: {summary['extracted_facts_count']}")
    except Exception as e:
        logger.error(f"Error getting conversation summary: {e}")
        print("\nUnable to generate conversation summary.")


if __name__ == "__main__":
    main()
