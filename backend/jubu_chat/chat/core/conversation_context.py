import uuid
from typing import Optional

from infrastructure.logging import get_logger
from jubu_chat.chat.domain.entities import ChildProfile, ConversationContext
from jubu_chat.chat.domain.enums import ConversationState
from jubu_chat.chat.domain.value_objects import (
    ChitChatContext,
    EdutainmentContext,
    PretendPlayContext,
)

logger = get_logger(__name__)

# Global variable to hold the singleton instance
_conversation_context: Optional[ConversationContext] = None


def get_conversation_context() -> ConversationContext:
    """
    Get the conversation context singleton.

    This function ensures that a single instance of the ConversationContext
    is used throughout the application.
    """
    global _conversation_context

    if _conversation_context is None:
        # Create a proper default child profile with a valid ID
        default_child_id = str(uuid.uuid4())
        logger.info(f"Creating default child profile with ID: {default_child_id}")

        default_child_profile = ChildProfile(
            id=default_child_id, name="", age=0, interests=[], preferences={}
        )
        logger.info(f"Default child profile created: {default_child_profile}")

        # Create the conversation context with the default child profile
        _conversation_context = ConversationContext(
            conversation_history=[],
            child_profile=default_child_profile,
            child_facts=[],
            conversation_state=ConversationState.ACTIVE,
            chitchat_context=ChitChatContext(topics=[], sentiment=None, knowledge=[]),
            pretend_play_context=PretendPlayContext(
                topics=[], sentiment=None, knowledge=[], imagination_elements=[]
            ),
            edutainment_context=EdutainmentContext(
                topics=[],
                sentiment=None,
                knowledge=[],
                educational_topics=[],
                knowledge_demonstrated=[],
                questions_asked=[],
            ),
        )

        logger.info(
            f"Created singleton conversation context with child profile ID: {_conversation_context.child_profile.id}"
        )

    return _conversation_context
