"""
Configuration classes for KidsChat interactions.

This module provides strongly typed configuration classes for different
interaction types, ensuring type safety and validation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator


class ResponseFormatting(BaseModel):
    """Configuration for response formatting."""

    max_sentences: int = Field(
        3, description="Maximum number of sentences in a response"
    )
    max_words_per_sentence: int = Field(12, description="Maximum words per sentence")
    simplify_vocabulary: bool = Field(
        True, description="Whether to simplify vocabulary"
    )


class PersonalityConfig(BaseModel):
    """Configuration for assistant personality traits."""

    friendliness: int = Field(5, description="Friendliness level (1-5)")
    enthusiasm: int = Field(3, description="Enthusiasm level (1-5)")
    humor: int = Field(1, description="Humor level (1-5)")
    curiosity: int = Field(5, description="Curiosity level (1-5)")
    siliness: int = Field(5, description="Silliness level (1-5)")

    @validator("*")
    def validate_range(cls, v, values, **kwargs):
        """Validate that personality traits are in range 1-5."""
        if not isinstance(v, int) or v < 1 or v > 5:
            raise ValueError(
                f"Personality trait must be an integer between 1 and 5, got {v}"
            )
        return v


class ModelConfig(BaseModel):
    """Configuration for the language model."""

    provider: str = Field(
        ..., description="Model provider (e.g., 'google', 'anthropic')"
    )
    model_name: str = Field(..., description="Name of the model")
    temperature: float = Field(0.7, description="Temperature for generation")
    max_output_tokens: Optional[int] = Field(None, description="Maximum output tokens")
    max_input_tokens: Optional[int] = Field(None, description="Maximum input tokens")
    top_p: Optional[float] = Field(None, description="Top-p sampling parameter")
    frequency_penalty: Optional[float] = Field(None, description="Frequency penalty")


class InteractionInfo(BaseModel):
    """Basic information about an interaction."""

    name: str = Field(..., description="Name of the interaction")
    description: str = Field(..., description="Description of the interaction")
    icon: str = Field(..., description="Icon for the interaction")
    color: str = Field(..., description="Color for the interaction")


class PromptExample(BaseModel):
    """Example for prompt engineering."""

    child_input: str = Field(..., description="Example input from child")
    assistant_response: str = Field(..., description="Example response from assistant")


class FallbackResponses(BaseModel):
    """Fallback responses for different scenarios."""

    unclear_input: str = Field(..., description="Response for unclear input")
    inappropriate_topic: str = Field(
        ..., description="Response for inappropriate topics"
    )
    technical_error: str = Field(..., description="Response for technical errors")


class PromptConfig(BaseModel):
    """Configuration for prompts."""

    system: str = Field(..., description="System prompt")
    examples: List[PromptExample] = Field(
        default_factory=list, description="Example exchanges"
    )
    fallbacks: FallbackResponses = Field(..., description="Fallback responses")


class ConversationFlowConfig(BaseModel):
    """Configuration for conversation flow."""

    ask_follow_up_questions: bool = Field(
        True, description="Whether to ask follow-up questions"
    )
    maintain_topic_coherence: bool = Field(
        True, description="Whether to maintain topic coherence"
    )
    topic_switch_threshold: Optional[float] = Field(
        None, description="Threshold for topic switching"
    )
    scenario_development_pace: Optional[str] = Field(
        None, description="Pace of scenario development"
    )
    allow_child_direction: Optional[bool] = Field(
        None, description="Whether to allow child direction"
    )


class BaseInteractionConfig(BaseModel):
    """Base configuration for all interaction types."""

    interaction: InteractionInfo
    model: ModelConfig
    required_inputs: List[str] = Field(
        ..., description="Required inputs for the interaction"
    )
    response_formatting: ResponseFormatting
    personality: Optional[PersonalityConfig] = None
    prompts: PromptConfig


class ChitChatConfig(BaseInteractionConfig):
    """Configuration for chitchat interactions."""

    conversation_flow: ConversationFlowConfig


class PretendPlayConfig(BaseInteractionConfig):
    """Configuration for pretend play interactions."""

    conversation_flow: ConversationFlowConfig

    @validator("conversation_flow")
    def validate_conversation_flow(cls, v):
        # assert 0, f"v is {v}, type is {type(v)}, v.scenario_development_pace is {v.scenario_development_pace}"
        """Validate that pretend play has scenario development pace."""
        if not hasattr(v, "scenario_development_pace"):
            raise ValueError("Pretend play must specify scenario_development_pace")
        if not hasattr(v, "allow_child_direction"):
            raise ValueError("Pretend play must specify allow_child_direction")
        return v


class EdutainmentConfig(BaseInteractionConfig):
    """Configuration for edutainment interactions."""

    learning_approach: Dict[str, Any] = Field(
        default_factory=dict, description="Learning approach settings"
    )
