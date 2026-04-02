"""
Pydantic models for child profiles.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field, validator


class ChildProfileBase(BaseModel):
    """Base schema for child profiles."""
    name: str
    age: int = Field(..., ge=3, le=12)
    interests: Optional[List[str]] = []
    preferences: Optional[Dict[str, Any]] = {}


class ChildProfileCreate(ChildProfileBase):
    """Schema for creating a child profile."""
    pass


class ChildProfileUpdate(BaseModel):
    """Schema for updating a child profile."""
    name: Optional[str] = None
    age: Optional[int] = Field(None, ge=3, le=12)
    interests: Optional[List[str]] = None
    preferences: Optional[Dict[str, Any]] = None


class ChildProfileResponse(ChildProfileBase):
    """Schema for returning a child profile."""
    id: str
    parent_id: str
    created_at: datetime
    updated_at: datetime
    last_interaction: Optional[datetime] = None

    class Config:
        from_attributes = True