"""
Base model interface for KidsChat.

This module defines the common interface that all language models must implement,
ensuring consistent behavior across different model providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, Iterator, List, Optional, Union

from pydantic import BaseModel

from infrastructure.logging import get_logger

logger = get_logger(__name__)


class ModelRole(str, Enum):
    """Roles in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"


class GenerationTask(str, Enum):
    GENERATE = "generate"
    SAFETY_EVALUATE = "safety_evaluate"
    FACTS_EXTRACT = "facts_extract"
    INTERACTION_ANALYZE = "interaction_analyze"
    CAPABILITY_EVALUATE = "capability_evaluate"
    PARENT_SUMMARY = "parent_summary"


@dataclass
class Message:
    """A message in a conversation."""

    role: ModelRole
    content: str
    name: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None
    # Metadata
    interaction_type: Optional[str] = None


@dataclass
class ModelResponse:
    """Response from a language model."""

    content: str
    raw_response: Any
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    task: Optional[GenerationTask] = None


class BaseLanguageModel(ABC):
    """
    Abstract base class for all language models.

    This class defines the interface that all model implementations must follow,
    regardless of the underlying provider (OpenAI, Anthropic, Google, etc.).
    """

    def __init__(
        self,
        model_name: str,
        provider: str,
        temperature: float = 0.7,
        max_output_tokens: int = 1024,
        max_input_tokens: int = 8192,
        **kwargs,
    ):
        """
        Initialize the language model.

        Args:
            model_name: Name of the specific model to use
            provider: Provider of the model (e.g., "openai", "anthropic", "google")
            temperature: Sampling temperature (0.0 to 1.0)
            max_output_tokens: Maximum number of tokens to generate
            max_input_tokens: Maximum number of tokens to input
            **kwargs: Additional model-specific parameters
        """
        self.model_name = model_name
        self.provider = provider
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.max_input_tokens = max_input_tokens
        self.additional_params = kwargs

        # Initialize provider-specific client
        self._initialize_client()

        logger.info(
            f"Initialized {self.provider} model '{self.model_name}' "
            f"with temperature={self.temperature}, max_output_tokens={self.max_output_tokens}, "
            f"max_input_tokens={self.max_input_tokens}"
        )

    @abstractmethod
    def _initialize_client(self) -> None:
        """
        Initialize the provider-specific client.

        This method should set up any necessary API clients, authentication,
        and other provider-specific initialization.
        """
        pass

    @abstractmethod
    def generate(self, messages: List[Message], task: GenerationTask) -> ModelResponse:
        """
        Generate a response from the model.

        Args:
            messages: List of conversation messages

        Returns:
            ModelResponse containing the generated content
        """
        pass

    def generate_stream(
        self, messages: List[Message], task: GenerationTask
    ) -> Iterator[str]:
        """
        Stream a response token-by-token from the model.

        Default implementation calls generate() and yields the full content as one
        chunk.  Subclasses should override this for true streaming.
        """
        response = self.generate(messages, task)
        yield response.content

    def generate_with_prompt(self, prompt: str, task: GenerationTask) -> ModelResponse:
        """
        Generate a response from a single prompt.

        Args:
            prompt: The prompt text

        Returns:
            ModelResponse containing the generated content
        """
        return self.generate([Message(role=ModelRole.USER, content=prompt)], task=task)

    def format_messages_for_provider(self, messages: List[Message]) -> Any:
        """
        Format messages in the provider-specific format.

        Args:
            messages: List of standardized messages

        Returns:
            Provider-specific message format
        """
        # Default implementation returns the messages as-is
        # Subclasses should override this if needed
        return messages

    def __str__(self) -> str:
        """String representation of the model."""
        return f"{self.provider}/{self.model_name}"


# For backward compatibility
BaseModel = BaseLanguageModel
