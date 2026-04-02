"""
ChitChat interaction implementation for casual conversations.

This module implements the casual conversation interaction type,
focusing on friendly, engaging dialogue without specific educational goals.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.common.exceptions import ConfigurationError
from jubu_chat.chat.core.conversation_context import get_conversation_context
from jubu_chat.chat.domain.entities import ChildProfile, ConversationContext
from jubu_chat.chat.domain.enums import Sentiment
from jubu_chat.chat.domain.value_objects import ChildFact, ChitChatContext
from jubu_chat.chat.interactions.base_interaction import BaseInteraction
from jubu_chat.chat.interactions.interaction_config import PromptExample
from jubu_chat.chat.models.base_model import Message, ModelRole

logger = get_logger(__name__)


class ChitChatInteraction(BaseInteraction):
    """
    Implementation of casual conversation interactions.

    This interaction type handles general conversational exchanges,
    maintaining a friendly and age-appropriate tone.
    """

    def __init__(
        self, config_manager, conversation_context: Optional[ConversationContext] = None
    ):
        """
        Initialize the ChitChat interaction.

        Args:
            config_manager: Configuration manager instance
            conversation_context: Shared conversation context
        """
        super().__init__(config_manager)
        self.interaction_type = "chitchat"
        self.conversation_context = conversation_context or get_conversation_context()

        # Initialize chitchat-specific context if not already present
        if not self.conversation_context.chitchat_context:
            self.conversation_context.chitchat_context = ChitChatContext(
                topics=[], sentiment=None, knowledge=[]
            )

    def enhance_system_prompt(
        self,
        base_prompt: str,
        child_profile: ChildProfile,
        parent_input: Dict[str, Any],
        facts: List[ChildFact],
    ) -> str:
        """
        Enhance the system prompt with ChitChat-specific context.

        Args:
            base_prompt: Base system prompt
            child_profile: Profile information about the child from the database
            parent_input: Parental control settings from UI/database
            facts: List of facts about the child from the conversation history

        Returns:
            Enhanced system prompt
        """
        chitchat_context = self.conversation_context.chitchat_context

        # Add topics information if available
        enhanced_prompt = base_prompt
        if chitchat_context.topics:
            topics_info = f"\n\nRecent topics: {', '.join(chitchat_context.topics)}"
            enhanced_prompt += topics_info

        # Add sentiment information if available
        if chitchat_context.sentiment:
            sentiment_info = (
                f"\n\nChild's current sentiment: {chitchat_context.sentiment[0].value}"
            )
            enhanced_prompt += sentiment_info

        # Add personality configuration
        personality = self.get_config_value("personality", {})
        if personality:
            personality_info = "\n\nPersonality configuration:\n"
            for trait, value in personality.__dict__.items():
                personality_info += f"- {trait}: {value}\n"
            enhanced_prompt += personality_info

        # Add child interests from profile
        if child_profile.interests:
            interests_info = (
                f"\n\nChild's interests: {', '.join(child_profile.interests)}"
            )
            enhanced_prompt += interests_info

        # Add prohibited topics from parent input
        if "prohibited_topics" in parent_input and parent_input["prohibited_topics"]:
            prohibited_info = (
                f"\n\nProhibited topics: {', '.join(parent_input['prohibited_topics'])}"
            )
            enhanced_prompt += prohibited_info

        return enhanced_prompt

    def enhance_fact_extraction_prompt(self, base_prompt: str) -> str:
        """
        Enhance the fact extraction prompt with ChitChat-specific guidance.

        Args:
            base_prompt: Base fact extraction prompt

        Returns:
            Enhanced fact extraction prompt
        """
        chitchat_context = self.conversation_context.chitchat_context

        # Add context about previously identified topics
        enhanced_prompt = base_prompt
        if chitchat_context.topics:
            topics_info = f"\n\nPreviously identified topics: {', '.join(chitchat_context.topics)}"
            enhanced_prompt += topics_info
            enhanced_prompt += "\nLook for new topics the child might be interested in."

        # Add guidance for extracting preferences
        enhanced_prompt += "\n\nIn casual conversation, pay special attention to:"
        enhanced_prompt += "\n- Likes and dislikes expressed by the child"
        enhanced_prompt += "\n- Emotional reactions to topics"
        enhanced_prompt += "\n- Hobbies and activities mentioned"
        enhanced_prompt += "\n- Friends or family members referenced"

        # Add guidance for expected analysis output format
        enhanced_prompt += "\n\nReturn your analysis in the following JSON format:"
        enhanced_prompt += """\n{
            "topics": ["topic1", "topic2", ...],
            "sentiment": "positive|negative"
        }"""
        enhanced_prompt += "\nEnsure all fields are present. For sentiment, only use 'positive' or 'negative' values."
        logger.info(f"Enhanced prompt for chitchat facts extraction: {enhanced_prompt}")
        return enhanced_prompt

    def update_context_from_analysis(self, analysis_result: Dict[str, Any]) -> None:
        """
        Update the interaction context based on analysis results.

        Args:
            analysis_result: Analysis results from the model
        """
        chitchat_context = self.conversation_context.chitchat_context

        # Update topics if present in analysis
        if "topics" in analysis_result and analysis_result["topics"]:
            new_topics = analysis_result["topics"]
            chitchat_context.topics.extend(new_topics)
            # Keep only unique topics
            chitchat_context.topics = list(set(chitchat_context.topics))

        # Update sentiment if present in analysis
        if "sentiment" in analysis_result:
            sentiment_value = analysis_result["sentiment"].lower()
            if sentiment_value == "positive":
                chitchat_context.sentiment = (Sentiment.POSITIVE, datetime.now())
            elif sentiment_value == "negative":
                chitchat_context.sentiment = (Sentiment.NEGATIVE, datetime.now())
