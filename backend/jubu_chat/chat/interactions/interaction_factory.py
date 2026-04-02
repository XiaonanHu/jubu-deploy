"""
Factory for creating interaction instances.

This module provides a factory for creating and managing interaction instances
based on configuration and interaction type.
"""

from typing import Any, Dict, Type

from jubu_chat.chat.core.config_manager import ConfigManager
from jubu_chat.chat.interactions.base_interaction import BaseInteraction
from jubu_chat.chat.interactions.chitchat import ChitChatInteraction
from jubu_chat.chat.interactions.edutainment import EdutainmentInteraction
from jubu_chat.chat.interactions.pretend_play import PretendPlayInteraction


class InteractionFactory:
    """
    Factory for creating and managing interaction instances.

    This class is responsible for instantiating the appropriate interaction
    class based on the interaction type and configuration.
    """

    def __init__(self, config_manager: ConfigManager):
        """
        Initialize the interaction factory.

        Args:
            config_manager: System-wide configuration manager
        """
        self.config_manager = config_manager
        self._interaction_registry: Dict[str, Type[BaseInteraction]] = {}
        self._register_default_interactions()

    def _register_default_interactions(self) -> None:
        """Register the default interaction types."""
        self.register_interaction("chitchat", ChitChatInteraction)
        self.register_interaction("pretend_play", PretendPlayInteraction)
        self.register_interaction("edutainment", EdutainmentInteraction)
        # Register other interaction types here

    def register_interaction(
        self, interaction_id: str, interaction_class: Type[BaseInteraction]
    ) -> None:
        """
        Register an interaction type with its implementation class.

        Args:
            interaction_id: Unique identifier for the interaction type
            interaction_class: The implementation class for the interaction
        """
        self._interaction_registry[interaction_id] = interaction_class

    def create_interaction(self, interaction_id: str) -> BaseInteraction:
        """
        Create an instance of the specified interaction type.

        Args:
            interaction_id: Identifier for the interaction type to create

        Returns:
            An instance of the appropriate interaction class

        Raises:
            ValueError: If the interaction type is not registered
        """
        if interaction_id not in self._interaction_registry:
            raise ValueError(f"Unknown interaction type: {interaction_id}")

        # Load the interaction-specific configuration
        interaction_config = self.config_manager.load_interaction_config(interaction_id)

        # Create and return the interaction instance
        interaction_class = self._interaction_registry[interaction_id]
        return interaction_class(
            interaction_id, interaction_config, self.config_manager
        )

    def get_available_interactions(self) -> Dict[str, str]:
        """
        Get a dictionary of available interaction types and their descriptions.

        Returns:
            Dictionary mapping interaction IDs to their descriptions
        """
        interactions = {}
        for interaction_id in self._interaction_registry:
            config = self.config_manager.load_interaction_config(interaction_id)
            description = ""
            if "interaction" in config and "description" in config["interaction"]:
                description = config["interaction"]["description"]
            interactions[interaction_id] = description
        return interactions
