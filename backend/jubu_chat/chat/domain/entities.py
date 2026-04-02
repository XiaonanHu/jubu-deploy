from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from jubu_chat.chat.domain.enums import ConversationState
from jubu_chat.chat.domain.value_objects import (
    ChildFact,
    ChitChatContext,
    ConversationTurn,
    EdutainmentContext,
    PretendPlayContext,
)
from jubu_datastore.dto.entities import ChildProfile, User  # re-export


class ConversationContext(BaseModel):
    """Context for a conversation."""

    conversation_history: List[ConversationTurn]
    child_profile: ChildProfile
    child_facts: List[ChildFact]
    conversation_state: ConversationState
    chitchat_context: ChitChatContext
    pretend_play_context: PretendPlayContext
    edutainment_context: EdutainmentContext
