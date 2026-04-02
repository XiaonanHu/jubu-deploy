"""
Common type definitions for the Jubu Chat system.
"""

from typing import Optional

from pydantic import BaseModel


class TurnResponse(BaseModel):
    """
    Defines the expected JSON structure for a standard conversational turn from the LLM.
    """

    system_response: str
    child_name: Optional[str] = None
    # Deprecated: interaction type is no longer determined by the model.
    # Kept for backward compatibility with existing stored data.
    current_interaction: Optional[str] = None
