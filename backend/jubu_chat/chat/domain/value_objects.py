"""
Immutable objects that represent concepts with attributes but no identity.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from jubu_chat.chat.domain.enums import Sentiment


class ChildFact(BaseModel):
    """A fact extracted about the child during conversation."""

    content: str
    confidence: float
    expiration: datetime
    timestamp: datetime = Field(default_factory=datetime.now)
    source_message_id: Optional[str] = None
    verified: bool = False


class ConversationTurn(BaseModel):
    """A single turn in the conversation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    child_message: str = ""
    system_message: str = ""
    interaction_type: str = "chitchat"
    timestamp: datetime = Field(default_factory=datetime.now)
    safety_evaluation: Dict[str, Any] = Field(default_factory=dict)


class ParentInput(BaseModel):
    """
    Parental inputs to the conversation.
    """

    prohibited_topics: List[str]


# Interaction context
class InteractionContext(BaseModel):
    """
    Base class for an interaction context.
    """

    topics: List[str]
    sentiment: Optional[Tuple[Sentiment, datetime]] = None
    knowledge: List[str]


class ChitChatContext(InteractionContext):
    """
    Context for a chit chat interaction.
    """

    pass


class PretendPlayContext(InteractionContext):
    """
    Context for a pretend play interaction.
    """

    imagination_elements: List[str]


class EdutainmentContext(InteractionContext):
    """
    Context for an edutainment interaction.
    """

    educational_topics: List[str]
    knowledge_demonstrated: List[str]
    questions_asked: List[str]
