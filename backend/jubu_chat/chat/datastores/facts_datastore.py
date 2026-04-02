"""Re-export from jubu_datastore for backward compatibility."""

from jubu_datastore.facts_datastore import ChildFactModel, FactsDatastore

__all__ = ["FactsDatastore", "ChildFactModel"]
