"""
Pydantic models for conversations.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field


class ConversationTurnBase(BaseModel):
    """Base schema for conversation turns."""
    child_message: str
    system_message: Optional[str] = None
    interaction_type: str
    timestamp: datetime
    safety_evaluation: Optional[Dict[str, Any]] = None


class ConversationTurnResponse(ConversationTurnBase):
    """Schema for returning a conversation turn."""
    id: str
    conversation_id: str

    class Config:
        from_attributes = True


class ConversationBase(BaseModel):
    """Base schema for conversations."""
    child_id: str
    state: str
    start_time: datetime
    end_time: Optional[datetime] = None
    last_interaction_time: datetime
    metadata: Optional[Dict[str, Any]] = None
    is_archived: bool = False


class ConversationResponse(ConversationBase):
    """Schema for returning a conversation summary."""
    id: str
    turn_count: int

    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationBase):
    """Schema for returning detailed conversation information."""
    id: str
    turns: List[ConversationTurnResponse]

    class Config:
        from_attributes = True


class ConversationParentInsightsResponse(BaseModel):
    """Summary and suggestions for parents (per-conversation)."""
    summary: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)