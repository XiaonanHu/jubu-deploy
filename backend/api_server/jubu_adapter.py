"""
Adapter for KidsChat functionality.

This module provides an adapter that interfaces with the KidsChat system,
allowing the API server to initialize and interact with conversations.
"""

import base64
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.core.config_manager import BaseConfig, ConfigManager
from jubu_chat.chat.core.conversation_manager import ConversationManager
from jubu_chat.chat.core.turn_state import TurnState
from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory

# Import KidsChat components
from jubu_chat.chat.domain.enums import ConversationState
from jubu_chat.chat.models.gemini_model import GeminiModel
from jubu_chat.chat.models.model_factory import ModelFactory
from speech_services.speech_to_text import initialize_stt_service
from speech_services.text_to_speech import initialize_tts_service

# Configure logging
logger = get_logger(__name__)


class ConversationNotFoundError(Exception):
    """Raised when a requested conversation is not found."""

    pass


class JubuAdapter:
    """
    Adapter for KidsChat functionality.

    This class initializes and manages KidsChat conversations,
    providing methods for processing audio input and checking conversation status.
    """

    def __init__(self):
        """Initialize the JubuAdapter."""
        # Get config directory
        self.config_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "jubu_chat", "configs"
        )
        logger.info(f"Using config directory: {self.config_dir}")

        # Initialize config manager
        self.config_manager = ConfigManager(BaseConfig, config_dir=self.config_dir)

        # Initialize model factory
        self.model_factory = ModelFactory(self.config_manager)
        self.model_factory.register_provider("google", GeminiModel)

        # Store active conversations
        self.active_conversations: Dict[str, Dict[str, Any]] = {}

        # Create temporary directory for audio files
        os.makedirs("temp_audio", exist_ok=True)

    # ------------------------------------------------------------------
    # TurnState helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_age_bucket(age: int) -> str:
        """Map a child's integer age to the matching age bucket string."""
        if age <= 5:
            return "3-5"
        if age <= 8:
            return "6-8"
        return "9-10"

    def get_turn_state(self, conversation_id: str) -> Optional[TurnState]:
        """Return the TurnState for an active conversation, or None."""
        entry = self.active_conversations.get(conversation_id)
        return entry.get("turn_state") if entry else None

    def save_turn_state(self, conversation_id: str, state: TurnState) -> None:
        """Persist an updated TurnState back into the in-memory store."""
        if conversation_id in self.active_conversations:
            self.active_conversations[conversation_id]["turn_state"] = state

    # ------------------------------------------------------------------

    def is_conversation_active(self, conversation_id: str) -> bool:
        """Check if a conversation is active."""
        return conversation_id in self.active_conversations

    def get_conversation_history(
        self, conversation_id: str, last_n: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the conversation history for a given conversation.

        Args:
            conversation_id: The ID of the conversation.
            last_n: The number of last turns to retrieve. If None, retrieves all.

        Returns:
            A list of conversation turns.
        """
        if conversation_id not in self.active_conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        conversation_manager = self.active_conversations[conversation_id][
            "conversation_manager"
        ]
        history = (
            conversation_manager.get_conversation_history()
        )  # Assuming this method exists

        if last_n:
            return history[-last_n:]
        return history

    def get_stt_service(self, conversation_id: str) -> Optional[Any]:
        """Get the STT service for a conversation."""
        if conversation_id in self.active_conversations:
            return self.active_conversations[conversation_id].get("stt_service")
        return None

    def get_tts_service(self, conversation_id: str) -> Optional[Any]:
        """Get the TTS service for a conversation."""
        if conversation_id in self.active_conversations:
            return self.active_conversations[conversation_id].get("tts_service")
        return None

    def is_streaming_tts_enabled(self, conversation_id: str) -> bool:
        """Check if streaming TTS is enabled for a conversation."""
        if conversation_id in self.active_conversations:
            return bool(
                self.active_conversations[conversation_id].get("streaming_tts", False)
            )
        return False

    def initialize_conversation(
        self,
        conversation_id: str,
        interaction_type: Optional[str] = None,
        model: Optional[str] = None,
        child_id: Optional[str] = None,
        child_profile_path: Optional[str] = None,
        stt_provider: str = "google",
        tts_provider: str = "elevenlabs",
        tts_voice: Optional[str] = None,
        streaming_tts: bool = False,
    ) -> Dict[str, Any]:
        """
        Initialize a new conversation.

        Args:
            conversation_id: Unique identifier for the conversation
            interaction_type: Type of interaction (e.g., "chitchat", "storytelling")
            model: Model to use for the conversation
            child_id: ID of an existing child profile to use
            child_profile_path: Path to a JSON file containing child profile information
            stt_provider: Speech-to-text provider to use
            tts_provider: Text-to-speech provider to use
            tts_voice: Voice ID or name to use for TTS
            streaming_tts: Enable streaming TTS for this conversation

        Returns:
            Dict containing initial system response and other information
        """
        # Create runtime overrides based on parameters
        runtime_overrides = {}
        if model:
            runtime_overrides["conversation"] = {"model": model}
        # interaction_type parameter is accepted but ignored — always uses chitchat (unified prompt)

        # Create configuration
        config = self.config_manager.create_all_configs(
            runtime_overrides=runtime_overrides
        )

        # Load child profile if provided
        child_profile = None
        if child_id:
            # Load profile from database
            profile_datastore = DatastoreFactory.create_profile_datastore()
            profile = profile_datastore.get(child_id)
            if profile:
                # Convert Pydantic model to dict
                if hasattr(profile, "model_dump"):
                    child_profile = profile.model_dump()
                else:
                    child_profile = profile.dict()
                logger.info(
                    f"Loaded child profile from database: {profile.name}, age: {profile.age}"
                )
            else:
                logger.warning(f"Child profile with ID {child_id} not found")
        elif child_profile_path:
            try:
                with open(child_profile_path, "r") as f:
                    child_profile = json.load(f)
                logger.info(f"Loaded child profile from {child_profile_path}")
            except Exception as e:
                logger.error(f"Failed to load child profile: {e}")

        # Initialize STT service
        stt_service, stt_success = initialize_stt_service(
            stt_provider,
            5,  # Default duration
            continuous_mode=True,
            language_code="en",  # Default to English
        )

        if not stt_success:
            logger.error(
                f"Failed to initialize STT service with provider {stt_provider}"
            )
            raise RuntimeError(
                f"Failed to initialize STT service with provider {stt_provider}"
            )

        # Initialize TTS service
        tts_service, tts_success = initialize_tts_service(tts_provider, tts_voice)

        if not tts_success:
            logger.error(
                f"Failed to initialize TTS service with provider {tts_provider}"
            )
            raise RuntimeError(
                f"Failed to initialize TTS service with provider {tts_provider}"
            )

        # Create conversation manager
        if child_id:
            conversation_manager = ConversationManager(
                config=config, child_id=child_id, model_factory=self.model_factory
            )
        else:
            conversation_manager = ConversationManager(
                config=config,
                child_profile=child_profile,
                model_factory=self.model_factory,
            )

        # Get initial system message (greeting)
        initial_response = self._get_initial_greeting(conversation_manager)

        # Generate audio for the greeting (keep batch greeting regardless of streaming flag)
        audio_data = None
        try:
            tts_start_time = time.time()
            # Generate audio bytes
            audio_bytes = self._generate_audio(tts_service, initial_response)
            if audio_bytes:
                # Encode as base64
                audio_data = base64.b64encode(audio_bytes).decode("utf-8")
            tts_end_time = time.time()
            logger.info(
                f"LATENCY-b| tts.greeting_batch | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int((tts_end_time - tts_start_time)*1000)}"
            )
        except Exception as e:
            logger.error(f"Failed to generate audio for greeting: {e}")

        # Derive age bucket from child profile
        child_age = (
            getattr(conversation_manager.conversation_context.child_profile, "age", 5)
            or 5
        )
        age_bucket = self._derive_age_bucket(int(child_age))

        # Store conversation data
        self.active_conversations[conversation_id] = {
            "conversation_manager": conversation_manager,
            "stt_service": stt_service,
            "tts_service": tts_service,
            "config": config,
            "streaming_tts": bool(streaming_tts),
            "start_time": time.time(),
            "turn_state": TurnState(age_bucket=age_bucket),
        }

        return {
            "child_id": conversation_manager.conversation_context.child_profile.id,
            "system_response": initial_response,
            "interaction_type": config.conversation.default_interaction.value,
            "audio_data": audio_data,
        }

    def _get_initial_greeting(self, conversation_manager: ConversationManager) -> str:
        """
        Get the initial greeting for a conversation.

        Since the original ConversationManager doesn't have a get_initial_greeting method,
        we'll generate a standard greeting based on the conversation context.

        Args:
            conversation_manager: The conversation manager instance

        Returns:
            A greeting message
        """
        return "Hi, I am Boojoo. What should we talk about today?"

    def _generate_audio(self, tts_service, text):
        """
        Generate audio bytes for the given text.

        Args:
            tts_service: The TTS service instance
            text: Text to convert to speech

        Returns:
            Audio bytes if successful, None otherwise
        """
        try:
            # Try different methods based on what's available in the TTS service

            # Method 1: Direct bytes generation
            if hasattr(tts_service, "generate_audio_bytes") and callable(
                getattr(tts_service, "generate_audio_bytes")
            ):
                return tts_service.generate_audio_bytes(text)

            # Method 2: Alternative method name
            elif hasattr(tts_service, "generate_audio") and callable(
                getattr(tts_service, "generate_audio")
            ):
                return tts_service.generate_audio(text)

            # Method 3: Synthesize method
            elif hasattr(tts_service, "synthesize") and callable(
                getattr(tts_service, "synthesize")
            ):
                return tts_service.synthesize(text)

            # Method 4: Try the provider directly
            elif hasattr(tts_service, "provider") and tts_service.provider:
                provider = tts_service.provider
                if hasattr(provider, "generate_audio_bytes") and callable(
                    getattr(provider, "generate_audio_bytes")
                ):
                    return provider.generate_audio_bytes(text)
                elif hasattr(provider, "synthesize") and callable(
                    getattr(provider, "synthesize")
                ):
                    return provider.synthesize(text)

            # If no direct method, use temporary file approach
            temp_path = f"temp_audio/temp_{uuid.uuid4()}.mp3"
            if hasattr(tts_service, "speak_text") and callable(
                getattr(tts_service, "speak_text")
            ):
                # Attempt to redirect the audio output to a file
                # This is a fallback approach that may not work with all providers
                original_audio = tts_service.speak_text(text, play_audio=False)
                if isinstance(original_audio, bytes):
                    return original_audio

            # If all else fails
            logger.error("Could not find a suitable method to generate audio bytes")
            return None

        except Exception as e:
            logger.error(f"Failed to generate TTS audio: {e}")
            return None

    def process_audio_input(
        self, conversation_id: str, audio_path: str
    ) -> Dict[str, Any]:
        """
        Process audio input for a conversation.

        Args:
            conversation_id: ID of the conversation
            audio_path: Path to the audio file to process

        Returns:
            Dict containing system response and other information

        Raises:
            ConversationNotFoundError: If the conversation is not found
        """
        # Check if conversation exists
        if conversation_id not in self.active_conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        conversation_data = self.active_conversations[conversation_id]
        conversation_manager = conversation_data["conversation_manager"]
        stt_service = conversation_data["stt_service"]
        tts_service = conversation_data["tts_service"]

        # Transcribe audio
        transcription = stt_service.transcribe_from_file(audio_path)
        if not transcription:
            transcription = "(No speech detected)"
            logger.warning(
                f"No speech detected in audio file for conversation {conversation_id}"
            )

        logger.info(
            f"Transcription for conversation {conversation_id}: {transcription}"
        )

        # Process the turn
        response_dict = conversation_manager.process_turn(transcription)

        # Generate audio for the response
        audio_data = None
        try:
            tts_start_time = time.time()
            # Generate audio bytes
            audio_bytes = self._generate_audio(
                tts_service, response_dict["system_response"]
            )
            if audio_bytes:
                # Encode as base64
                audio_data = base64.b64encode(audio_bytes).decode("utf-8")
            tts_end_time = time.time()
            logger.info(
                f"LATENCY-b| tts.turn_batch | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int((tts_end_time - tts_start_time)*1000)}"
            )
        except Exception as e:
            logger.error(f"Failed to generate audio for response: {e}")

        return {
            "system_response": response_dict["system_response"],
            "interaction_type": response_dict.get("interaction_type", "unknown"),
            "audio_data": audio_data,
            "transcription": transcription,
        }

    def process_turn(self, conversation_id: str, user_input: str) -> Dict[str, Any]:
        """
        Process a conversation turn with text input.

        Args:
            conversation_id: ID of the conversation
            user_input: User's text input

        Returns:
            Dict containing system response and other information

        Raises:
            ConversationNotFoundError: If the conversation is not found
        """
        # Check if conversation exists
        if conversation_id not in self.active_conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        conversation_data = self.active_conversations[conversation_id]
        conversation_manager = conversation_data["conversation_manager"]
        tts_service = conversation_data["tts_service"]

        # All conversational logic, including name recognition, is now handled
        # by the ConversationManager. This adapter's role is simplified.
        turn_start = time.time()
        response_dict = conversation_manager.process_turn(user_input)
        turn_end = time.time()
        logger.info(
            f"Latency: Adapter process_turn (LLM+logic) dt={turn_end - turn_start:.4f}s"
        )

        # Generate audio for the response
        audio_data = None
        try:
            tts_start_time = time.time()
            # Generate audio bytes
            audio_bytes = self._generate_audio(
                tts_service, response_dict["system_response"]
            )
            if audio_bytes:
                # Encode as base64
                audio_data = base64.b64encode(audio_bytes).decode("utf-8")
            tts_end_time = time.time()
            logger.info(
                f"LATENCY-b| tts.text_input_batch | iso={datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} | dt_ms={int((tts_end_time - tts_start_time)*1000)}"
            )
        except Exception as e:
            logger.error(f"Failed to generate audio for response: {e}")

        return {
            "system_response": response_dict["system_response"],
            "interaction_type": response_dict.get("interaction_type", "unknown"),
            "audio_data": audio_data,
        }

    def process_turn_text_only(
        self, conversation_id: str, user_input: str
    ) -> Dict[str, Any]:
        """
        Process a conversation turn but return only text fields (no TTS generation).
        """
        if conversation_id not in self.active_conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        conversation_data = self.active_conversations[conversation_id]
        conversation_manager = conversation_data["conversation_manager"]
        turn_start = time.time()
        response_dict = conversation_manager.process_turn(user_input)
        turn_end = time.time()
        logger.info(
            f"Latency: Adapter process_turn_text_only (LLM+logic) dt={turn_end - turn_start:.4f}s"
        )
        return {
            "system_response": response_dict["system_response"],
            "interaction_type": response_dict.get("interaction_type", "unknown"),
        }

    def get_response_stream(self, conversation_id: str, user_input: str):
        """
        Return a (token_iterator, finalize_fn) pair for LLM streaming.

        token_iterator  -- synchronous blocking generator of raw text tokens from
                           the LLM.  Designed to be consumed inside a thread-pool
                           executor so that the async event loop is not blocked.
        finalize_fn(full_text) -- call once all tokens have been consumed to
                                  persist the turn, run safety callback and trigger
                                  summarization.

        Raises ConversationNotFoundError if the conversation does not exist.
        """
        if conversation_id not in self.active_conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        cm = self.active_conversations[conversation_id]["conversation_manager"]
        turn_state = self.get_turn_state(conversation_id)

        # Increment turn counter before building the prompt
        if turn_state is not None:
            turn_state.turn_count += 1

        # Start safety evaluation immediately, in parallel with LLM streaming.
        # The future is passed through to finalize_fn so the callback can update
        # TurnState once the result arrives (without blocking the stream).
        safety_start_time = time.time()
        safety_future = cm.executor.submit(cm._evaluate_safety, user_input)

        token_iter = cm._stream_response_tokens(user_input, turn_state=turn_state)

        def finalize_fn(full_text: str) -> None:
            cm.finalize_streaming_turn(
                user_input,
                full_text,
                turn_state=turn_state,
                safety_future=safety_future,
                safety_start_time=safety_start_time,
            )

        return token_iter, finalize_fn

    def get_conversation_status(self, conversation_id: str) -> Dict[str, Any]:
        """
        Get the status of a conversation.

        Args:
            conversation_id: ID of the conversation

        Returns:
            Dict containing conversation status information

        Raises:
            ConversationNotFoundError: If the conversation is not found
        """
        # Check if conversation exists
        if conversation_id not in self.active_conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        conversation_data = self.active_conversations[conversation_id]
        conversation_manager = conversation_data["conversation_manager"]

        # Get conversation summary
        summary = conversation_manager.get_conversation_summary()

        # Add conversation state
        summary["state"] = conversation_manager.state.value

        return summary

    def cleanup_conversation_resources(self, conversation_id: str):
        """Clean up resources for a specific conversation."""
        if conversation_id not in self.active_conversations:
            logger.warning(f"Conversation {conversation_id} not found for cleanup")
            return

        try:
            conversation_data = self.active_conversations[conversation_id]
            conversation_manager = conversation_data["conversation_manager"]

            # End the conversation properly
            if conversation_manager.state != ConversationState.ENDED:
                conversation_manager.end_conversation()

            # Remove from active conversations
            del self.active_conversations[conversation_id]
            logger.info(f"Cleaned up conversation {conversation_id}")
        except Exception as e:
            logger.error(f"Error cleaning up conversation {conversation_id}: {e}")

    def cleanup_resources(self):
        """Clean up resources for all active conversations."""
        for conversation_id, conversation_data in self.active_conversations.items():
            try:
                # End the conversation properly
                conversation_manager = conversation_data["conversation_manager"]
                if conversation_manager.state != ConversationState.ENDED:
                    conversation_manager.end_conversation()
                logger.info(f"Ended conversation {conversation_id}")
            except Exception as e:
                logger.error(f"Error ending conversation {conversation_id}: {e}")
