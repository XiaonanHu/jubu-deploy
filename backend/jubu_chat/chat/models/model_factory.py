"""
Model factory for creating language model instances.

This module provides a factory for creating instances of different
language models based on configuration.
"""

from typing import Any, Dict, Optional, Type

from infrastructure.logging import get_logger
from jubu_chat.chat.common.exceptions import (
    ModelInitializationError,
    ModelNotFoundError,
)
from jubu_chat.chat.core.config_manager import ConfigManager, ModelConfig
from jubu_chat.chat.models.base_model import BaseLanguageModel

logger = get_logger(__name__)


class ModelFactory:
    """Factory for creating language model instances."""

    # Registry of model provider implementations
    _provider_registry: Dict[str, Type[BaseLanguageModel]] = {}

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the model factory.

        Args:
            config_manager: Optional configuration manager instance
        """
        self.config_manager = config_manager

    @classmethod
    def register_provider(
        cls, provider_name: str, model_class: Type[BaseLanguageModel]
    ) -> None:
        """
        Register a model provider implementation.

        Args:
            provider_name: Name of the provider (e.g., "openai", "anthropic", "google")
            model_class: Implementation class for the provider
        """
        cls._provider_registry[provider_name.lower()] = model_class
        logger.info(f"Registered model provider: {provider_name}")

    def create_model(
        self,
        model_name: str,
        config_manager: Optional[ConfigManager] = None,
        model_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> BaseLanguageModel:
        """
        Create a language model instance.

        Args:
            model_name: Name of the model to create
            config_manager: Optional configuration manager (overrides the one set in constructor)
            model_config: Optional explicit model configuration (bypasses config_manager)
            **kwargs: Additional parameters to pass to the model constructor

        Returns:
            Instance of a BaseLanguageModel implementation

        Raises:
            ModelNotFoundError: If the model or provider is not supported
            ModelInitializationError: If the model initialization fails
        """
        # Determine the configuration source
        cm = config_manager or self.config_manager

        # Get model configuration
        if model_config:
            # Use explicitly provided configuration
            config = ModelConfig(**model_config)
        elif cm:
            # Load from configuration manager
            try:
                model_config_dict = cm.load_model_config(model_name)
                config = ModelConfig(**model_config_dict)
            except Exception as e:
                logger.error(f"Failed to load model config for '{model_name}': {e}")
                raise ModelNotFoundError(f"Invalid model name: {model_name}")
        else:
            # No configuration source available
            raise ValueError("Either config_manager or model_config must be provided")

        # Get the provider implementation
        provider = config.provider.lower()
        if provider not in self._provider_registry:
            available_providers = ", ".join(self._provider_registry.keys())
            logger.error(
                f"Provider '{provider}' not registered. Available providers: {available_providers}"
            )
            raise ModelNotFoundError(f"Unsupported model provider: {provider}")

        model_class = self._provider_registry[provider]

        # Create and return the model instance
        try:
            # Merge configuration with any override kwargs
            model_params = {
                "model_name": config.model_name,
                "provider": provider,
                "temperature": config.temperature,
                "max_output_tokens": config.max_output_tokens,
                "max_input_tokens": config.max_input_tokens,
                "top_p": config.top_p,
                "top_k": config.top_k,
                "presence_penalty": config.presence_penalty,
                "frequency_penalty": config.frequency_penalty,
            }

            # Override with any explicitly provided kwargs
            model_params.update(kwargs)

            model_instance = model_class(**model_params)
            logger.info(f"Created model instance: {model_instance}")
            return model_instance
        except Exception as e:
            logger.error(f"Failed to create model instance: {e}")
            raise ModelInitializationError(f"Failed to initialize model: {str(e)}")

    @classmethod
    def create_model_from_config(
        cls, config_manager: ConfigManager, model_name: Optional[str] = None
    ) -> BaseLanguageModel:
        """
        Create a language model instance based on configuration.

        This is a compatibility method for existing code that uses the old interface.

        Args:
            config_manager: Configuration manager instance
            model_name: Optional override for the model name in config

        Returns:
            Configured language model instance
        """
        factory = cls(config_manager)

        if model_name:
            return factory.create_model(model_name)
        else:
            # Use the model from the current merged configuration
            config = config_manager.get_config()
            try:
                # Extract model configuration from the merged config
                model_config_dict = config.model.dict()
                return factory.create_model(
                    model_name=model_config_dict.get("model_name", "default"),
                    model_config=model_config_dict,
                )
            except Exception as e:
                logger.error(f"Failed to extract model config from merged config: {e}")
                raise ModelNotFoundError(
                    "No valid model configuration found in current config"
                )

    @classmethod
    def get_available_providers(cls) -> list:
        """
        Get a list of available model providers.

        Returns:
            List of provider names
        """
        return list(cls._provider_registry.keys())
