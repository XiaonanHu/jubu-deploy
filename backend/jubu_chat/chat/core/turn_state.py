"""
Per-conversation runtime state for Boojoo.

Stored in-memory inside JubuAdapter.active_conversations. Lives for the
duration of one session (no Redis needed). Carries context that is injected
into the system prompt each turn via a [STATE] header.
"""

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class SafetyTag(str, Enum):
    """Categories returned by the safety evaluation model."""

    PERSONAL_INFORMATION = "personal_information"
    """Child shares or is asked for full name, parents' names, address, phone, school, etc. Not child's first name only."""

    SENSITIVE_TOPICS = "sensitive_topics"
    """Sex, drugs, death, violence, self-harm, suicide, abuse, war, weapons."""

    INAPPROPRIATE_LANGUAGE = "inappropriate_language"
    """Profanity, slurs, bullying, hate speech, explicit language."""

    MANIPULATION = "manipulation"
    """Jailbreak attempts, 'ignore your instructions', social engineering."""

    EMOTIONAL_DISTRESS = "emotional_distress"
    """Child expresses extreme sadness, fear, loneliness, anxiety, anger.
    Not inherently unsafe but signals the LLM should shift to a calm/supportive tone."""


class SafetyFlag(str, Enum):
    SAFE = "safe"
    SENSITIVE = (
        "sensitive"  # low-severity tags present; guide LLM via [SAFETY OVERRIDE]
    )
    UNSAFE = "unsafe"  # medium/high severity; stronger [SAFETY OVERRIDE] + redaction


class SceneMemory(BaseModel):
    """Tracks the current story/pretend-play scene. Populated by the summarizer."""

    character_name: str = ""
    setting: str = ""
    goal: str = ""
    special_object: str = ""


class TurnState(BaseModel):
    """
    Runtime state for a single conversation session.

    Loaded at the start of every user turn from JubuAdapter.active_conversations,
    updated in callbacks (safety eval, summarization), and read next turn to
    build the [STATE] header that is prepended to the system prompt.
    """

    age_bucket: str = "3-5"
    """One of '3-5', '6-8', '9-10'. Derived from ChildProfile.age at session start."""

    safety_flag: SafetyFlag = SafetyFlag.SAFE
    """Flag set by the previous turn's safety evaluation callback."""

    safety_tags: List[SafetyTag] = Field(default_factory=list)
    """Detailed tags from the previous turn's safety evaluation."""

    rolling_summary: str = ""
    """Short (≤400 chars) summary of the conversation so far, updated by summarizer."""

    scene_memory: SceneMemory = Field(default_factory=SceneMemory)
    """Key story/play elements tracked by the summarizer."""

    turn_count: int = 0
    """Number of completed turns. Incremented at the start of each streaming turn."""
