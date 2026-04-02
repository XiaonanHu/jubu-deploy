"""
Configuration management system for KidsChat.

This module provides a hierarchical configuration system that loads and merges
configuration from multiple sources with validation using Pydantic models.
"""

import os
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

import yaml
from pydantic import BaseModel, Field, validator

from infrastructure.logging import get_logger
from jubu_chat.chat.common.exceptions import (
    ConfigFileNotFoundError,
    ConfigParsingError,
    ConfigValidationError,
)
from jubu_chat.chat.interactions.interaction_config import (
    BaseInteractionConfig,
    ChitChatConfig,
    EdutainmentConfig,
    PretendPlayConfig,
)

logger = get_logger(__name__)


class ConfigSource(Enum):
    """Enum representing different configuration sources."""

    BASE = auto()
    INTERACTION = auto()
    MODEL = auto()
    EXPERIMENT = auto()
    USER_PROFILE = auto()
    PARENTAL_SETTINGS = auto()
    RUNTIME = auto()


class LogLevel(str, Enum):
    """Valid log levels for the application."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TelemetryProvider(str, Enum):
    """Supported telemetry providers."""

    LANGFUSE = "langfuse"
    OPENTELEMETRY = "opentelemetry"
    PROMETHEUS = "prometheus"
    NONE = "none"


class ContentFilterLevel(str, Enum):
    """Content filter levels for safety."""

    STRICT = "strict"
    MODERATE = "moderate"
    MINIMAL = "minimal"


class ChatInteractionType(str, Enum):
    """Available chat interactions in the system."""

    CHITCHAT = "chitchat"
    EDUTAINMENT = "edutainment"
    EMOTIONAL_SUPPORT = "emotional_support"
    INTERACTIVE_STORY = "interactive_story"
    LANGUAGE_LEARNING = "language_learning"
    MATH_LEARNING = "math_learning"
    PRETEND_PLAY = "pretend_play"
    STORYTELLING = "storytelling"
    TOOL_CALLING = "tool_calling"


class SystemConfig(BaseModel):
    """System-wide configuration settings."""

    name: str = "KidsChat"
    version: str = "1.0.0"
    log_level: LogLevel = LogLevel.INFO
    telemetry_provider: TelemetryProvider = TelemetryProvider.LANGFUSE
    config_dir: Optional[str] = None


class ConversationConfig(BaseModel):
    """Configuration for chat mode detection."""

    model: str
    threshold: float = Field(ge=0.0, le=1.0)
    default_interaction: ChatInteractionType = ChatInteractionType.CHITCHAT


class FactsExtractionConfig(BaseModel):
    """Configuration for extracting and managing facts about the child."""

    model: str
    short_term_retention_hours: int = Field(ge=1, le=168)  # Max 1 week


class SafetyEvaluation(str, Enum):
    """Safety evaluation levels."""

    SAFE = "safe"
    MODERATE = "moderate"
    UNSAFE = "unsafe"


class SafetyEvaluationConfig(BaseModel):
    """Configuration for safety evaluation."""

    model: str
    threshold: float = Field(ge=0.0, le=1.0)
    default_safety_evaluation: SafetyEvaluation = SafetyEvaluation.MODERATE


class SafetyConfig(BaseModel):
    """Safety and content filtering configuration."""

    content_filter_level: ContentFilterLevel = ContentFilterLevel.STRICT
    inappropriate_topics: List[str] = []
    age_appropriate_language: bool = True
    max_consecutive_unsafe_attempts: int = Field(ge=1, le=10)


class SpeechConfig(BaseModel):
    """Text-to-speech and speech-to-text configuration."""

    text_to_speech_provider: str
    speech_to_text_provider: str
    default_voice: str
    default_speed: float = Field(ge=0.5, le=2.0)


class MemoryConfig(BaseModel):
    """Configuration for memory settings."""

    conversation_history_length: int = Field(ge=1, default=10)
    persistent_storage: bool = True  # Whether to use persistent storage


class CapabilityEvaluationConfig(BaseModel):
    """Optional configuration for capability evaluation at conversation end."""

    enabled: bool = False
    run_at_end: bool = True
    model: Optional[str] = None  # If None, use conversation model
    max_turns: Optional[int] = Field(default=20, ge=1, le=200)
    max_chars: Optional[int] = Field(default=15000, ge=100, le=100000)


class ParentSummaryConfig(BaseModel):
    """Optional configuration for parent-facing summary at conversation end."""

    enabled: bool = False
    run_at_end: bool = True
    model: Optional[str] = None
    max_summary_words: int = Field(default=200, ge=10, le=1000)
    max_turns: Optional[int] = Field(default=20, ge=1, le=200)
    max_chars: Optional[int] = Field(default=15000, ge=100, le=100000)


class BaseConfig(BaseModel):
    """Root configuration model that contains all system-wide settings."""

    system: SystemConfig
    conversation: ConversationConfig
    facts_extraction: FactsExtractionConfig
    safety_evaluation: SafetyEvaluationConfig
    safety: SafetyConfig
    speech: SpeechConfig
    memory: MemoryConfig
    capability_evaluation: Optional[CapabilityEvaluationConfig] = None
    parent_summary: Optional[ParentSummaryConfig] = None


class ModelConfig(BaseModel):
    """Configuration for a specific LLM."""

    provider: str
    model_name: str
    temperature: float = Field(ge=0.0, le=2.0)
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=0)
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)


class ResponseFormattingConfig(BaseModel):
    """Configuration for formatting responses to children."""

    max_sentences: int = Field(ge=1)
    max_words_per_sentence: int = Field(ge=1)
    simplify_vocabulary: bool = True
    use_emojis: bool = True


class PromptConfig(BaseModel):
    """Configuration for prompts used in a specific mode."""

    system: str
    examples: List[Dict[str, str]] = []


class InteractionConfig(BaseModel):
    """Configuration for a specific chat mode."""

    interaction: Dict[str, str]
    model: ModelConfig
    required_inputs: List[str]
    response_formatting: ResponseFormattingConfig
    prompts: PromptConfig


T = TypeVar("T", bound=BaseModel)


class ConfigManager(Generic[T]):
    """
    Manages configuration loading, validation, and merging from multiple sources.

    This class handles the hierarchical configuration system, loading configs from
    files and other sources, validating them using Pydantic models, and providing
    access to the merged configuration.
    """

    def __init__(self, config_model: Type[T], config_dir: Optional[str] = None):
        """
        Initialize the configuration manager.

        Args:
            config_model: The Pydantic model class to use for validation
            config_dir: Directory containing configuration files (optional)
        """
        self.config_model = config_model
        self.config_dir = config_dir or os.path.join(
            os.path.dirname(__file__), "../../configs"
        )
        self.config_cache: Dict[str, Dict[str, Any]] = {}
        self.merged_config: Optional[T] = None
        self.interaction_configs: Dict[str, Dict[str, Any]] = {}

    def get_interaction_config(self, interaction_id: str) -> BaseInteractionConfig:
        """
        Get a preloaded interaction configuration.

        Args:
            interaction_id: The interaction type to get configuration for

        Returns:
            Dictionary containing the interaction configuration

        Raises:
            KeyError: If the interaction configuration hasn't been loaded
        """
        cache_key = f"interaction_{interaction_id}"
        if cache_key not in self.config_cache:
            raise KeyError(f"Interaction configuration not loaded: {interaction_id}")
        return self.config_cache[cache_key]

    def get_all_interaction_names(self) -> List[str]:
        """
        Get a list of all available interaction names.

        Returns:
            List of interaction names that have been loaded
        """
        interaction_names = []
        prefix = f"interaction_"
        for key in self.config_cache:
            if key.startswith(prefix):
                interaction_names.append(key[len(prefix) :])
        return interaction_names

    def initialize_app_config(
        self,
        model: Optional[str] = None,
        experiment_id: Optional[str] = None,
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ) -> T:
        """
        Initialize the application configuration at startup.

        This loads the base configuration, preloads all interaction configs,
        and creates the initial merged configuration.

        Args:
            model: Default model to use
            experiment_id: Experiment ID to apply
            runtime_overrides: Runtime configuration overrides

        Returns:
            Validated configuration object
        """
        return self.create_all_configs(
            model=model,
            experiment_id=experiment_id,
            runtime_overrides=runtime_overrides,
        )

    def load_yaml_config(self, config_path: str) -> Dict[str, Any]:
        """
        Load a YAML configuration file.

        Args:
            config_path: Path to the YAML file

        Returns:
            Dictionary containing the configuration

        Raises:
            ConfigFileNotFoundError: If the file does not exist
            ConfigParsingError: If the file cannot be parsed
        """
        if not os.path.exists(config_path):
            raise ConfigFileNotFoundError(
                f"Configuration file not found: {config_path}"
            )

        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigParsingError(f"Failed to parse YAML file {config_path}: {e}")
        except Exception as e:
            raise ConfigParsingError(
                f"Error loading configuration from {config_path}: {e}"
            )

    def load_base_config(self) -> Dict[str, Any]:
        """
        Load the base configuration.

        Returns:
            Dictionary containing the base configuration
        """
        try:
            base_config_path = os.path.join(self.config_dir, "base_config.yaml")
            return self.load_yaml_config(base_config_path)
        except Exception as e:
            logger.error(f"Failed to load base configuration: {e}")
            raise ConfigFileNotFoundError(
                "Base configuration not found or invalid"
            ) from e

    def _validate_interaction_config(
        self, config_obj: BaseInteractionConfig, interaction_id: str
    ) -> None:
        """
        Validate an interaction configuration object.

        Checks that all required fields are present and have valid values.

        Args:
            config_obj: The configuration object to validate
            interaction_id: The interaction identifier (for error messages)

        Raises:
            ConfigValidationError: If validation fails
        """
        # Required top-level fields
        required_fields = ["interaction", "model", "prompts"]
        for field in required_fields:
            if not hasattr(config_obj, field):
                raise ConfigValidationError(
                    f"Missing required field '{field}' in interaction config: {interaction_id}"
                )

        # Validate interaction metadata
        if (
            not hasattr(config_obj.interaction, "name")
            or not config_obj.interaction.name
        ):
            raise ConfigValidationError(
                f"Missing or empty 'interaction.name' in config: {interaction_id}"
            )

        # Validate model configuration
        if not hasattr(config_obj.model, "provider") or not config_obj.model.provider:
            raise ConfigValidationError(
                f"Missing or empty 'model.provider' in config: {interaction_id}"
            )

        if (
            not hasattr(config_obj.model, "model_name")
            or not config_obj.model.model_name
        ):
            raise ConfigValidationError(
                f"Missing or empty 'model.model_name' in config: {interaction_id}"
            )

        # Validate temperature is in valid range
        if hasattr(config_obj.model, "temperature"):
            temp = config_obj.model.temperature
            if not (0.0 <= temp <= 2.0):
                raise ConfigValidationError(
                    f"Invalid temperature {temp} in config {interaction_id}. Must be between 0.0 and 2.0."
                )

        # Validate prompts
        if not hasattr(config_obj.prompts, "system") or not config_obj.prompts.system:
            raise ConfigValidationError(
                f"Missing or empty 'prompts.system' in config: {interaction_id}"
            )

        # Validate system prompt is not too short (likely a mistake)
        if len(config_obj.prompts.system.strip()) < 20:
            logger.warning(
                f"System prompt in {interaction_id} is suspiciously short ({len(config_obj.prompts.system)} chars). "
                f"This may be a configuration error."
            )

        logger.debug(f"Validation passed for interaction config: {interaction_id}")

    def load_interaction_config(
        self, interaction_id: str
    ) -> Union[
        BaseInteractionConfig, ChitChatConfig, PretendPlayConfig, EdutainmentConfig
    ]:
        """
        Load configuration for a specific interaction type.

        Args:
            interaction_id: The identifier for the interaction type

        Returns:
            Strongly typed configuration object for the interaction

        Raises:
            FileNotFoundError: If the interaction configuration file doesn't exist
            ConfigValidationError: If the configuration is invalid
        """
        cache_key = f"interaction_{interaction_id}"
        if cache_key in self.config_cache:
            return self.config_cache[cache_key]

        # Determine the path to the interaction config file
        interaction_config_path = os.path.join(
            self.config_dir, "interactions", f"{interaction_id}.yaml"
        )

        # Check if the file exists
        if not os.path.exists(interaction_config_path):
            raise FileNotFoundError(
                f"No configuration found for interaction: {interaction_id}"
            )

        # Load the raw configuration
        config_data = self.load_yaml_config(interaction_config_path)

        # Convert to appropriate config class based on interaction type
        try:
            if interaction_id == "chitchat":
                config_obj = ChitChatConfig(**config_data)
            elif interaction_id == "pretend_play":
                config_obj = PretendPlayConfig(**config_data)
            elif interaction_id == "edutainment":
                config_obj = EdutainmentConfig(**config_data)
            else:
                config_obj = BaseInteractionConfig(**config_data)

            # Validate the configuration
            self._validate_interaction_config(config_obj, interaction_id)

            self.config_cache[cache_key] = config_obj
            return config_obj
        except ConfigValidationError:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            raise ConfigValidationError(
                f"Error loading interaction configuration for {interaction_id}: {str(e)}"
            )

    def load_model_config(self, model_name: str) -> Dict[str, Any]:
        """
        Load configuration for a specific model.

        Args:
            model_name: Name of the model

        Returns:
            Dictionary containing the model configuration
        """
        try:
            model_config_path = os.path.join(
                self.config_dir, "models", f"{model_name}.yaml"
            )
            return self.load_yaml_config(model_config_path)
        except ConfigFileNotFoundError:
            logger.warning(f"Model configuration not found for: {model_name}")
            return {}
        except Exception as e:
            logger.error(f"Error loading model configuration for {model_name}: {e}")
            return {}

    def load_experiment_config(self, experiment_id: str) -> Dict[str, Any]:
        """
        Load configuration for a specific experiment.

        Args:
            experiment_id: ID of the experiment

        Returns:
            Dictionary containing the experiment configuration
        """
        try:
            experiment_config_path = os.path.join(
                self.config_dir, "experiments", f"{experiment_id}.yaml"
            )
            return self.load_yaml_config(experiment_config_path)
        except ConfigFileNotFoundError:
            logger.warning(f"Experiment configuration not found for: {experiment_id}")
            raise
        except Exception as e:
            logger.error(
                f"Error loading experiment configuration for {experiment_id}: {e}"
            )
            raise ConfigParsingError(
                f"Failed to load experiment configuration: {str(e)}"
            )

    def merge_configs(self, *configs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge multiple configuration dictionaries.

        Later configurations override earlier ones for the same keys.

        Args:
            *configs: Configuration dictionaries to merge

        Returns:
            Merged configuration dictionary
        """
        result = {}
        for config in configs:
            self._deep_merge(result, config)
        return result

    def _deep_merge(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Recursively merge source dictionary into target dictionary.

        Args:
            target: Target dictionary to merge into
            source: Source dictionary to merge from
        """
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def create_all_configs(
        self,
        model: Optional[str] = None,
        experiment_id: Optional[str] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        parental_settings: Optional[Dict[str, Any]] = None,
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ) -> T:
        """
        Create a configuration by merging from multiple sources.

        Args:
            model: Model to load configuration for (optional)
            experiment_id: Experiment ID to load configuration for (optional)
            user_profile: User profile configuration (optional)
            parental_settings: Parental settings configuration (optional)
            runtime_overrides: Runtime configuration overrides (optional)

        Returns:
            Validated configuration object
        """
        base_config = self.load_base_config()

        self._preload_all_interactions()

        configs = [base_config]

        model_to_load = model if model else base_config["conversation"]["model"]
        configs.append(self.load_model_config(model_to_load))

        if experiment_id:
            try:
                configs.append(self.load_experiment_config(experiment_id))
            except FileNotFoundError:
                logger.warning(
                    f"Experiment configuration not found for: {experiment_id}"
                )

        if user_profile:
            configs.append({"user_profile": user_profile})

        if parental_settings:
            configs.append({"parental_settings": parental_settings})

        if runtime_overrides:
            configs.append(runtime_overrides)

        merged_config = self.merge_configs(*configs)

        validated_config = self.config_model(**merged_config)
        self.merged_config = validated_config

        return validated_config

    def get_config(self) -> T:
        """
        Get the current merged configuration.

        Returns:
            Current configuration object

        Raises:
            RuntimeError: If no configuration has been created yet
        """
        if self.merged_config is None:
            raise RuntimeError(
                "No configuration has been created yet. Call create_all_configs() first."
            )
        return self.merged_config

    def _preload_all_interactions(self) -> None:
        """
        Preload all interaction configurations at startup.

        This ensures all interaction configs are available immediately when needed
        during a conversation without file I/O delays.
        """
        interactions_dir = os.path.join(self.config_dir, "interactions")
        if not os.path.exists(interactions_dir):
            logger.warning(f"Interactions directory not found: {interactions_dir}")
            return

        loaded_count = 0
        # TODO: remove this
        interaction_files = ["pretend_play.yaml", "edutainment.yaml", "chitchat.yaml"]
        # for filename in os.listdir(interactions_dir):
        for filename in interaction_files:
            if filename.endswith(".yaml"):
                interaction_name = filename[:-5]  # Remove .yaml extension
                try:
                    self.load_interaction_config(interaction_name)
                    loaded_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to load interaction config {interaction_name}: {e}"
                    )

        logger.info(f"Preloaded {loaded_count} interaction configurations")
