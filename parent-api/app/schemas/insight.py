"""
Response schemas for parent insight (child discoveries) payload.
Matches the contract expected by the parent app UI.
"""

from typing import List, Optional

from pydantic import BaseModel


class ParentInsightItemSchema(BaseModel):
    """One capability item with label and status for the parent app."""
    item_id: str
    subsection_id: str
    subsection_display_name: str
    parent_friendly_label: str
    status: str  # "demonstrated" | "emerging" | "not_observed"
    mastery_score: float = 0.0
    evidence_snippet: Optional[str] = None


class ParentInsightFrameworkSchema(BaseModel):
    """One framework/category with its items."""
    framework_id: str
    framework_display_name: str
    items: List[ParentInsightItemSchema]


class ParentInsightPayloadSchema(BaseModel):
    """Full parent insight payload for one child."""
    child_id: str
    child_name: str
    summary_sentence: str
    frameworks: List[ParentInsightFrameworkSchema]
    suggested_next_activity: Optional[str] = None
