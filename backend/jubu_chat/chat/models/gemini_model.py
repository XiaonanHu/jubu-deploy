"""
Gemini model implementation for KidsChat.

This module provides an implementation of the BaseLanguageModel interface
for Google's Gemini models.
"""

import os
import threading
from typing import Any, Dict, Iterator, List, Optional

import google.auth
from google.ai.generativelanguage_v1beta import GenerativeServiceClient
from google.ai.generativelanguage_v1beta import types as glm_types
from google.api_core.client_options import ClientOptions
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import service_account

from infrastructure.logging import get_logger
from jubu_chat.chat.common.exceptions import (
    AuthenticationError,
    ModelInferenceError,
    ModelInitializationError,
)
from jubu_chat.chat.models.base_model import (
    BaseLanguageModel,
    GenerationTask,
    Message,
    ModelResponse,
    ModelRole,
)

logger = get_logger(__name__)


def _get_max_concurrency() -> int:
    try:
        value = int(os.getenv("GEMINI_MAX_CONCURRENCY", "2"))
        if value < 1:
            raise ValueError("value must be >= 1")
        return value
    except Exception as exc:
        logger.warning(
            f"Invalid GEMINI_MAX_CONCURRENCY value '{os.getenv('GEMINI_MAX_CONCURRENCY')}'. Falling back to 2. ({exc})"
        )
        return 2


_GEMINI_MAX_CONCURRENCY = _get_max_concurrency()
_GEMINI_CONCURRENCY_SEMAPHORE = threading.Semaphore(_GEMINI_MAX_CONCURRENCY)
logger.info(f"Gemini global concurrency limit set to {_GEMINI_MAX_CONCURRENCY}")

_GEMINI_DEFAULT_SCOPES = ["https://www.googleapis.com/auth/generative-language"]


class GeminiModel(BaseLanguageModel):
    """Implementation of the BaseLanguageModel interface for Google's Gemini models."""

    def __init__(
        self,
        model_name: str,
        provider: str,
        temperature: float = 0.7,
        max_output_tokens: int = 8192,
        max_input_tokens: int = 1,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Gemini model.

        Args:
            model_name: Name of the Gemini model to use
            provider: Provider name (should be "google")
            temperature: Sampling temperature (0.0 to 1.0)
            max_output_tokens: Maximum number of tokens to generate
            top_p: Top-p sampling parameter
            top_k: Top-k sampling parameter
            **kwargs: Additional parameters to pass to the model

        Raises:
            ModelInitializationError: If initialization fails
            AuthenticationError: If API key is missing or invalid
        """
        # Store these attributes directly in this class
        self.top_p = top_p
        self.top_k = top_k

        # Call the parent class constructor
        super().__init__(
            model_name=model_name,
            provider=provider,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            **kwargs,
        )

    def _initialize_client(self) -> None:
        """
        Initialize the Gemini client.

        This method sets up the Gemini API client with the appropriate
        authentication and configuration.

        Raises:
            AuthenticationError: If the API key is missing
            ModelInitializationError: If initialization fails
        """
        credential_source = None
        try:
            credentials = None
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

            if service_account_path:
                try:
                    credentials = service_account.Credentials.from_service_account_file(
                        service_account_path,
                        scopes=_GEMINI_DEFAULT_SCOPES,
                    )
                    credential_source = f"service account ({service_account_path})"
                    logger.info("Using service account credentials for Gemini model.")
                except Exception as exc:
                    logger.error(
                        f"Failed to load Gemini service account credentials from {service_account_path}: {exc}"
                    )
                    raise AuthenticationError(
                        f"Failed to load Gemini service account credentials: {exc}"
                    ) from exc

            if credentials is None and api_key is None:
                try:
                    credentials, project_id = google.auth.default(
                        scopes=_GEMINI_DEFAULT_SCOPES
                    )
                    credential_source = (
                        f"application default credentials (project={project_id})"
                    )
                    logger.info(
                        f"Using application default credentials for Gemini model (project={project_id})."
                    )
                except DefaultCredentialsError:
                    pass

            if credentials:
                self._client = GenerativeServiceClient(credentials=credentials)
            elif api_key:
                credential_source = "API key"
                client_options = ClientOptions(api_key=api_key)
                self._client = GenerativeServiceClient(client_options=client_options)
                logger.info("Using API key authentication for Gemini model.")
            else:
                raise AuthenticationError(
                    "No Gemini authentication found. Set GOOGLE_APPLICATION_CREDENTIALS to a service account key with "
                    "Generative Language access, or provide GEMINI_API_KEY / GOOGLE_API_KEY."
                )

            logger.info(
                f"Initialized Gemini model '{self.model_name}' using {credential_source}."
            )
        except AuthenticationError:
            # Re-raise authentication errors
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            raise ModelInitializationError(
                f"Failed to initialize Gemini model: {str(e)}"
            )

    def _create_generation_config(self) -> glm_types.GenerationConfig:
        """
        Create a generation configuration for the model.

        Returns:
            GenerationConfig object with model parameters
        """
        config_params: Dict[str, Any] = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
        }

        if hasattr(self, "top_p") and self.top_p is not None:
            config_params["top_p"] = self.top_p

        if hasattr(self, "top_k") and self.top_k is not None:
            config_params["top_k"] = self.top_k

        for key, value in self.additional_params.items():
            if value is not None:
                config_params[key] = value

        return glm_types.GenerationConfig(**config_params)

    def _format_messages(self, messages: List[Message]) -> List[glm_types.Content]:
        """
        Format messages for the Gemini API.

        Args:
            messages: List of Message objects

        Returns:
            List of formatted messages for the Gemini API
        """
        formatted_messages: List[glm_types.Content] = []
        system_segments = [
            message.content
            for message in messages
            if message.role == ModelRole.SYSTEM and message.content
        ]
        system_prefix = "\n\n".join(
            segment.strip() for segment in system_segments if segment.strip()
        )

        first_user_seen = False

        for message in messages:
            if message.role == ModelRole.SYSTEM:
                continue

            # Handle user messages
            if message.role == ModelRole.USER:
                content = message.content
                if not first_user_seen:
                    if system_prefix:
                        content = f"{system_prefix}\n\n{content}".strip()
                    first_user_seen = True

                formatted_messages.append(
                    glm_types.Content(
                        role="user",
                        parts=[glm_types.Part(text=content)],
                    )
                )

            # Handle assistant messages
            elif message.role == ModelRole.ASSISTANT:
                # Get interaction type from metadata
                content = message.content

                formatted_messages.append(
                    glm_types.Content(
                        role="model",
                        parts=[glm_types.Part(text=content)],
                    )
                )

            # Handle any other message types
            else:
                role = "user" if message.role == ModelRole.USER else "model"
                formatted_messages.append(
                    glm_types.Content(
                        role=role,
                        parts=[glm_types.Part(text=message.content)],
                    )
                )

        return formatted_messages

    def generate(self, messages: List[Message], task: GenerationTask) -> ModelResponse:
        """
        Generate a response from the model.

        Args:
            messages: List of conversation messages
            task: The type of generation task

        Returns:
            ModelResponse containing the generated content

        Raises:
            ModelInferenceError: If generation fails
        """
        try:

            # Format messages for Gemini
            formatted_messages = self._format_messages(messages)
            model_resource = (
                self.model_name
                if self.model_name.startswith("models/")
                else f"models/{self.model_name}"
            )

            # Generate content with global concurrency control
            with _GEMINI_CONCURRENCY_SEMAPHORE:
                request = glm_types.GenerateContentRequest(
                    model=model_resource,
                    contents=formatted_messages,
                    generation_config=self._create_generation_config(),
                )
                response = self._client.generate_content(request=request)
            logger.debug(f"formatted_messages {formatted_messages}")

            # Extract the response text
            if not response.candidates or not response.candidates[0].content.parts:
                logger.warning("Gemini returned an empty response")
                return ModelResponse(
                    content="",
                    raw_response=response,
                    finish_reason="empty_response",
                    task=task,
                )

            # For thinking models (e.g. gemini-2.5-flash / gemini-3-flash-preview),
            # the response may contain thought parts + actual response parts.
            # We extract only non-thought text parts.
            parts = response.candidates[0].content.parts
            text_parts = []
            for part in parts:
                is_thought = getattr(part, "thought", False)
                text = getattr(part, "text", None)
                if text and not is_thought:
                    text_parts.append(text)

            if text_parts:
                content = "\n".join(text_parts)
            else:
                # Fallback: if all parts are thought parts or no text found,
                # use the last part's text (likely the actual response)
                content = parts[-1].text if hasattr(parts[-1], "text") else ""

            finish_reason = response.candidates[0].finish_reason or "unknown"

            logger.debug(f"Raw model response:\n{content}")

            # Return the raw content - parsing will be handled by JSONParser
            return ModelResponse(
                content=content,
                raw_response=response,
                finish_reason=finish_reason,
                task=task,
            )
        except Exception as e:
            logger.error(f"Error generating content with Gemini: {e}")
            raise ModelInferenceError(f"Failed to generate content: {str(e)}")

    def generate_stream(
        self, messages: List[Message], task: GenerationTask
    ) -> Iterator[str]:
        """
        Stream a response from Gemini token-by-token using stream_generate_content.

        This is a synchronous blocking generator intended to be called from a
        thread-pool executor.  Yields raw text fragments as they arrive so that
        downstream consumers (TTS pipeline) can start processing before the full
        response is available.
        """
        try:
            formatted_messages = self._format_messages(messages)
            model_resource = (
                self.model_name
                if self.model_name.startswith("models/")
                else f"models/{self.model_name}"
            )

            with _GEMINI_CONCURRENCY_SEMAPHORE:
                request = glm_types.GenerateContentRequest(
                    model=model_resource,
                    contents=formatted_messages,
                    generation_config=self._create_generation_config(),
                )
                for response in self._client.stream_generate_content(request=request):
                    if not response.candidates:
                        continue
                    for part in response.candidates[0].content.parts:
                        if getattr(part, "thought", False):
                            continue
                        text = getattr(part, "text", None)
                        if text:
                            yield text
        except Exception as e:
            logger.error(f"Error streaming content from Gemini: {e}")
            raise

    def generate_with_prompt(self, prompt: str, task: GenerationTask) -> ModelResponse:
        """
        Generate a response from a single prompt.

        Args:
            prompt: The prompt text

        Returns:
            ModelResponse containing the generated content

        Raises:
            ModelInferenceError: If generation fails
        """
        return self.generate([Message(role=ModelRole.USER, content=prompt)], task=task)
