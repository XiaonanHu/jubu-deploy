"""Re-export from jubu_datastore for backward compatibility."""

from jubu_datastore.base_datastore import BaseDatastore
from jubu_datastore.conversation_datastore import ConversationDatastore
from jubu_datastore.datastore_factory import DatastoreFactory
from jubu_datastore.facts_datastore import FactsDatastore
from jubu_datastore.interaction_contexts_datastore import InteractionContextsDatastore
from jubu_datastore.profile_datastore import ProfileDatastore
from jubu_datastore.story_datastore import StoryDatastore
from jubu_datastore.user_datastore import UserDatastore

__all__ = [
    "BaseDatastore",
    "ConversationDatastore",
    "FactsDatastore",
    "ProfileDatastore",
    "InteractionContextsDatastore",
    "StoryDatastore",
    "UserDatastore",
    "DatastoreFactory",
]

# Optional capability datastore and registry (may not exist in minimal/stub installs)
try:
    from jubu_datastore.capability_datastore import CapabilityDatastore
    from jubu_datastore.loaders import (
        CapabilityDefinitionRegistry,
        load_default_registry,
    )

    __all__ = [
        *__all__,
        "CapabilityDatastore",
        "CapabilityDefinitionRegistry",
        "load_default_registry",
    ]
except ImportError:
    CapabilityDatastore = None  # type: ignore[misc, assignment]
    CapabilityDefinitionRegistry = None  # type: ignore[misc, assignment]
    load_default_registry = None  # type: ignore[misc, assignment]
