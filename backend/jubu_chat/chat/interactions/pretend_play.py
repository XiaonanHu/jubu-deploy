"""
Pretend Play interaction implementation for imaginative scenarios.

This module implements the pretend play interaction type, which engages
children in imaginative scenarios and role-playing activities.
"""

from typing import Any, Dict, List, Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.common.exceptions import ConfigurationError
from jubu_chat.chat.core.conversation_context import get_conversation_context
from jubu_chat.chat.domain.entities import ChildProfile, ConversationContext
from jubu_chat.chat.domain.value_objects import ChildFact, PretendPlayContext
from jubu_chat.chat.interactions.base_interaction import BaseInteraction
from jubu_chat.chat.interactions.interaction_config import PromptExample
from jubu_chat.chat.models.base_model import Message, ModelRole

logger = get_logger(__name__)


class PretendPlayInteraction(BaseInteraction):
    """
    Implementation of pretend play interactions.

    This interaction type handles imaginative scenarios and role-playing,
    encouraging creativity and storytelling.
    """

    def __init__(
        self, config_manager, conversation_context: Optional[ConversationContext] = None
    ):
        """
        Initialize the PretendPlay interaction.

        Args:
            config_manager: Configuration manager instance
            conversation_context: Shared conversation context
        """
        super().__init__(config_manager)
        self.conversation_context = conversation_context or get_conversation_context()
        self.interaction_type = "pretend_play"

        # Initialize pretend play-specific context if not already present
        if (
            not hasattr(self.conversation_context, "pretend_play_context")
            or not self.conversation_context.pretend_play_context
        ):
            self.conversation_context.pretend_play_context = PretendPlayContext(
                topics=[], sentiment=None, knowledge=[], imagination_elements=[]
            )

    def enhance_system_prompt(
        self,
        base_prompt: str,
        child_profile: ChildProfile,
        parent_input: Dict[str, Any],
        facts: List[ChildFact],
    ) -> str:
        """
        Enhance the system prompt with PretendPlay-specific context.

        Args:
            base_prompt: Base system prompt
            child_profile: Profile information about the child
            parent_input: Parental control settings
            facts: List of facts about the child

        Returns:
            Enhanced system prompt
        """
        pretend_play_context = self.conversation_context.pretend_play_context

        # Add imagination elements if available
        enhanced_prompt = base_prompt
        if pretend_play_context.imagination_elements:
            elements_info = f"\n\nImagination elements in this play: {', '.join(pretend_play_context.imagination_elements)}"
            enhanced_prompt += elements_info

        # Add topics information if available
        if pretend_play_context.topics:
            topics_info = f"\n\nRecent topics: {', '.join(pretend_play_context.topics)}"
            enhanced_prompt += topics_info

        # Add personality configuration
        personality = self.get_config_value("personality", {})
        if personality:
            personality_info = "\n\nPersonality configuration:\n"
            for trait, value in personality.__dict__.items():
                personality_info += f"- {trait}: {value}\n"
            enhanced_prompt += personality_info

        # Add child interests from profile to inform pretend play scenarios
        if hasattr(child_profile, "interests") and child_profile.interests:
            interests_info = f"\n\nChild's interests for scenario development: {', '.join(child_profile.interests)}"
            enhanced_prompt += interests_info

        # Add prohibited topics from parent input
        if "prohibited_topics" in parent_input and parent_input["prohibited_topics"]:
            prohibited_info = (
                f"\n\nProhibited topics: {', '.join(parent_input['prohibited_topics'])}"
            )
            enhanced_prompt += prohibited_info

        # Add guidance for pretend play
        enhanced_prompt += "\n\nGuidelines for pretend play:"
        enhanced_prompt += "\n- Follow the child's lead in the scenario"
        enhanced_prompt += "\n- Encourage creative thinking and problem-solving"
        enhanced_prompt += "\n- Introduce new elements sparingly to enhance the play"
        enhanced_prompt += "\n- Keep the scenario age-appropriate and engaging"

        return enhanced_prompt

    def enhance_fact_extraction_prompt(self, base_prompt: str) -> str:
        """
        Enhance the fact extraction prompt with PretendPlay-specific guidance.

        Args:
            base_prompt: Base fact extraction prompt

        Returns:
            Enhanced fact extraction prompt
        """
        pretend_play_context = self.conversation_context.pretend_play_context

        # Add context about previously identified imagination elements
        enhanced_prompt = base_prompt
        if pretend_play_context.imagination_elements:
            elements_info = f"\n\nPreviously identified imagination elements: {', '.join(pretend_play_context.imagination_elements)}"
            enhanced_prompt += elements_info
            enhanced_prompt += (
                "\nLook for new imagination elements the child has introduced."
            )

        # Add guidance for extracting preferences in pretend play
        enhanced_prompt += "\n\nIn pretend play, pay special attention to:"
        enhanced_prompt += "\n- Characters the child creates or identifies with"
        enhanced_prompt += "\n- Scenarios and settings the child enjoys"
        enhanced_prompt += "\n- Problem-solving approaches demonstrated"
        enhanced_prompt += "\n- Emotional themes expressed through play"
        enhanced_prompt += "\n- Creative thinking patterns"
        enhanced_prompt += "\n- Imagination elements (e.g. magical powers, fantasy creatures, made-up places)"

        # Add guidance for expected analysis output format
        enhanced_prompt += "\n\nReturn your analysis in the following JSON format:"
        enhanced_prompt += """\n{
            "imagination_elements": ["element1", "element2", ...],
            "topics": ["topic1", "topic2", ...]
        }"""
        enhanced_prompt += "\nEnsure all fields are present even if empty arrays."
        logger.info(
            f"Enhanced prompt for pretend_play facts extraction: {enhanced_prompt}"
        )
        return enhanced_prompt

    def update_context_from_analysis(self, analysis_result: Dict[str, Any]) -> None:
        """
        Update the interaction context based on analysis results.

        Args:
            analysis_result: Analysis results from the model
        """
        pretend_play_context = self.conversation_context.pretend_play_context

        # Update imagination elements if present in analysis
        if (
            "imagination_elements" in analysis_result
            and analysis_result["imagination_elements"]
        ):
            new_elements = analysis_result["imagination_elements"]
            pretend_play_context.imagination_elements.extend(new_elements)
            # Keep only unique elements
            pretend_play_context.imagination_elements = list(
                set(pretend_play_context.imagination_elements)
            )

        # Update topics if present in analysis
        if "topics" in analysis_result and analysis_result["topics"]:
            new_topics = analysis_result["topics"]
            pretend_play_context.topics.extend(new_topics)
            # Keep only unique topics
            pretend_play_context.topics = list(set(pretend_play_context.topics))
