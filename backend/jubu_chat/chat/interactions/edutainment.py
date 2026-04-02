"""
Edutainment interaction implementation for educational content.

This module implements the edutainment interaction type, which delivers
educational content in an entertaining and engaging way for children.
"""

from typing import Any, Dict, List, Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.common.exceptions import ConfigurationError
from jubu_chat.chat.core.conversation_context import get_conversation_context
from jubu_chat.chat.domain.entities import ChildProfile, ConversationContext
from jubu_chat.chat.domain.value_objects import ChildFact, EdutainmentContext
from jubu_chat.chat.interactions.base_interaction import BaseInteraction
from jubu_chat.chat.interactions.interaction_config import PromptExample
from jubu_chat.chat.models.base_model import Message, ModelRole

logger = get_logger(__name__)


class EdutainmentInteraction(BaseInteraction):
    """
    Implementation of edutainment interactions.

    This interaction type handles educational content delivery in an
    entertaining way, making learning fun and engaging for children.
    """

    def __init__(
        self, config_manager, conversation_context: Optional[ConversationContext] = None
    ):
        """
        Initialize the Edutainment interaction.

        Args:
            config_manager: Configuration manager instance
            conversation_context: Shared conversation context
        """
        super().__init__(config_manager)
        self.conversation_context = conversation_context or get_conversation_context()

        self.interaction_type = "edutainment"
        # Initialize edutainment-specific context if not already present
        if (
            not hasattr(self.conversation_context, "edutainment_context")
            or not self.conversation_context.edutainment_context
        ):
            self.conversation_context.edutainment_context = EdutainmentContext(
                topics=[],
                sentiment=None,
                knowledge=[],
                educational_topics=[],
                knowledge_demonstrated=[],
                questions_asked=[],
            )

    def enhance_system_prompt(
        self,
        base_prompt: str,
        child_profile: ChildProfile,
        parent_input: Dict[str, Any],
        facts: List[ChildFact],
    ) -> str:
        """
        Enhance the system prompt with Edutainment-specific context.

        Args:
            base_prompt: Base system prompt
            child_profile: Profile information about the child
            parent_input: Parental control settings
            facts: List of facts about the child

        Returns:
            Enhanced system prompt
        """
        edutainment_context = self.conversation_context.edutainment_context

        # Add educational topics if available
        enhanced_prompt = base_prompt
        if edutainment_context.educational_topics:
            topics_info = f"\n\nEducational topics discussed: {', '.join(edutainment_context.educational_topics)}"
            enhanced_prompt += topics_info

        # Add knowledge demonstrated if available
        if edutainment_context.knowledge_demonstrated:
            knowledge_info = f"\n\nKnowledge demonstrated by the child: {', '.join(edutainment_context.knowledge_demonstrated)}"
            enhanced_prompt += knowledge_info

        # Add questions asked if available
        if edutainment_context.questions_asked:
            questions_info = f"\n\nQuestions asked by the child: {', '.join(edutainment_context.questions_asked)}"
            enhanced_prompt += questions_info

        # Add learning approach configuration
        learning_approach = self.get_config_value("learning_approach", {})
        if learning_approach:
            approach_info = "\n\nLearning approach configuration:\n"
            for key, value in learning_approach.items():
                approach_info += f"- {key}: {value}\n"
            enhanced_prompt += approach_info

        # Add personality configuration
        personality = self.get_config_value("personality", {})
        if personality:
            personality_info = "\n\nPersonality configuration:\n"
            for trait, value in personality.__dict__.items():
                personality_info += f"- {trait}: {value}\n"
            enhanced_prompt += personality_info

        # Add child age and interests from profile to tailor educational content
        if hasattr(child_profile, "age"):
            age_info = f"\n\nChild's age: {child_profile.age}"
            enhanced_prompt += age_info

        if hasattr(child_profile, "interests") and child_profile.interests:
            interests_info = f"\n\nChild's interests for educational content: {', '.join(child_profile.interests)}"
            enhanced_prompt += interests_info

        # Add prohibited topics from parent input
        if "prohibited_topics" in parent_input and parent_input["prohibited_topics"]:
            prohibited_info = (
                f"\n\nProhibited topics: {', '.join(parent_input['prohibited_topics'])}"
            )
            enhanced_prompt += prohibited_info

        # Add guidance for edutainment
        enhanced_prompt += "\n\nGuidelines for educational content:"
        enhanced_prompt += "\n- Present information in an age-appropriate way"
        enhanced_prompt += "\n- Use examples and analogies to explain concepts"
        enhanced_prompt += "\n- Encourage curiosity and critical thinking"
        enhanced_prompt += "\n- Make learning fun and engaging"
        enhanced_prompt += "\n- Ask questions to check understanding"

        return enhanced_prompt

    def enhance_fact_extraction_prompt(self, base_prompt: str) -> str:
        """
        Enhance the fact extraction prompt with Edutainment-specific guidance.

        Args:
            base_prompt: Base fact extraction prompt

        Returns:
            Enhanced fact extraction prompt
        """
        edutainment_context = self.conversation_context.edutainment_context

        # Add context about previously identified educational topics
        enhanced_prompt = base_prompt
        if edutainment_context.educational_topics:
            topics_info = f"\n\nPreviously identified educational topics: {', '.join(edutainment_context.educational_topics)}"
            enhanced_prompt += topics_info
            enhanced_prompt += "\nLook for new educational interests or topics the child is curious about."

        # Add context about previously demonstrated knowledge
        if edutainment_context.knowledge_demonstrated:
            knowledge_info = f"\n\nPreviously demonstrated knowledge: {', '.join(edutainment_context.knowledge_demonstrated)}"
            enhanced_prompt += knowledge_info
            enhanced_prompt += (
                "\nLook for new knowledge or understanding demonstrated by the child."
            )

        # Add guidance for extracting educational insights
        enhanced_prompt += "\n\nIn educational conversations, pay special attention to:"
        enhanced_prompt += "\n- Subject areas the child shows interest in"
        enhanced_prompt += "\n- Knowledge gaps that could be addressed"
        enhanced_prompt += "\n- Learning style preferences"
        enhanced_prompt += "\n- Questions that indicate curiosity"
        enhanced_prompt += "\n- Misconceptions that could be gently corrected"

        # Add guidance for expected analysis output format
        enhanced_prompt += "\n\nReturn your analysis in the following JSON format:"
        enhanced_prompt += """\n{
            "educational_topics": ["topic1", "topic2", ...],
            "knowledge_demonstrated": ["knowledge1", "knowledge2", ...],
            "question_asked": "specific question asked by child"
        }"""
        enhanced_prompt += (
            "\nEnsure all fields are present even if empty arrays or null values."
        )
        logger.info(
            f"Enhanced prompt for edutainment facts extraction: {enhanced_prompt}"
        )
        return enhanced_prompt

    def update_context_from_analysis(self, analysis_result: Dict[str, Any]) -> None:
        """
        Update the interaction context based on analysis results.

        Args:
            analysis_result: Analysis results from the model
        """
        edutainment_context = self.conversation_context.edutainment_context

        # Update educational topics if present in analysis
        if (
            "educational_topics" in analysis_result
            and analysis_result["educational_topics"]
        ):
            new_topics = analysis_result["educational_topics"]
            edutainment_context.educational_topics.extend(new_topics)
            # Keep only unique topics
            edutainment_context.educational_topics = list(
                set(edutainment_context.educational_topics)
            )

        # Update knowledge demonstrated if present in analysis
        if (
            "knowledge_demonstrated" in analysis_result
            and analysis_result["knowledge_demonstrated"]
        ):
            new_knowledge = analysis_result["knowledge_demonstrated"]
            edutainment_context.knowledge_demonstrated.extend(new_knowledge)
            # Keep only unique knowledge items
            edutainment_context.knowledge_demonstrated = list(
                set(edutainment_context.knowledge_demonstrated)
            )

        # Update questions asked if present in analysis
        if "question_asked" in analysis_result and analysis_result["question_asked"]:
            if "question_asked" in analysis_result:
                edutainment_context.questions_asked.append(
                    analysis_result["question_asked"]
                )
