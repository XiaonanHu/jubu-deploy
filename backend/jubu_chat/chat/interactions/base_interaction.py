"""
Base interaction class for KidsChat.

This module provides the base class for all interaction types,
defining the common interface and functionality.
"""

from typing import Any, Dict, List, Optional

from jubu_chat.chat.core.config_manager import ConfigManager
from jubu_chat.chat.core.conversation_context import get_conversation_context
from jubu_chat.chat.domain.entities import ChildProfile, ConversationContext
from jubu_chat.chat.domain.value_objects import ChildFact


class BaseInteraction:
    """
    Base class for all interaction types.

    This class defines the common interface that all interaction types
    must implement, as well as shared functionality.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        conversation_context: Optional[ConversationContext] = None,
    ):
        """
        Initialize the base interaction.

        Args:
            config_manager: Configuration manager instance
            conversation_context: Shared conversation context
        """
        self.config_manager = config_manager
        self.conversation_context = conversation_context or get_conversation_context()

    def get_config_value(self, key, default=None):
        """
        Get a configuration value for the current interaction type.

        Args:
            key: Configuration key
            default: Default value if key is not found

        Returns:
            Configuration value or default
        """
        try:
            interaction_config = self.config_manager.load_interaction_config(
                self.interaction_type
            )
            if hasattr(interaction_config, key):
                return getattr(interaction_config, key)
            return default
        except Exception:
            return default

    def enhance_system_prompt(
        self,
        base_prompt: str,
        child_profile: ChildProfile,
        parent_input: Dict[str, Any],
        facts: List[ChildFact],
    ) -> str:
        """
        Enhance the system prompt with interaction-specific and contextual information.

        CONTRACT: This method MUST return a prompt that:
        1. Preserves all base prompt instructions (do not remove or contradict)
        2. Adds child-specific context:
           - Child's name (if known): "You are talking to [name]"
           - Child's age (if known): "They are [age] years old"
           - Child's interests (if any): "They enjoy [interests]"
        3. Adds safety constraints:
           - Parent-prohibited topics: "Never discuss: [topics]"
           - Age-appropriate language reminders
        4. Adds relevant facts (limit to 5 most recent, high-confidence):
           - "Recent context: [facts]"

        This method MUST NOT:
        1. Remove or contradict base instructions from the interaction config
        2. Add response format instructions (JSON schema, etc.) - those are added separately
        3. Add interaction-switching logic - that's handled by the conversation manager

        Default Implementation:
        The base class provides a minimal implementation that adds child profile
        and safety context. Subclasses can override to add interaction-specific enhancements.

        Args:
            base_prompt: Base system prompt from interaction config
            child_profile: Profile information about the child (name, age, interests)
            parent_input: Parental control settings (prohibited_topics, etc.)
            facts: List of recent facts about the child from conversation history

        Returns:
            Enhanced system prompt with contextual information

        Example:
            Input base_prompt: "You are a friendly AI assistant..."
            Output: "You are a friendly AI assistant...\n
                     You are talking to Lily, who is 4 years old.\n
                     Lily enjoys dinosaurs and building blocks.\n
                     Never discuss: scary movies, violence.\n
                     Recent context: Lily mentioned having a pet dog."
        """
        # This method should be overridden by subclasses
        # Base implementation just returns the prompt unchanged
        return base_prompt

    def enhance_fact_extraction_prompt(self, base_prompt: str) -> str:
        """
        Enhance the fact extraction prompt with interaction-specific guidance.

        Args:
            base_prompt: Base fact extraction prompt

        Returns:
            Enhanced fact extraction prompt
        """
        # This method should be overridden by subclasses
        return base_prompt

    def update_context_from_analysis(self, analysis_result: Dict[str, Any]) -> None:
        """
        Update the interaction context based on analysis results.

        Args:
            analysis_result: Analysis results from the model
        """
        # This method should be overridden by subclasses
        pass
