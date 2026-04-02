"""Re-export from jubu_datastore for backward compatibility."""

from jubu_datastore.user_datastore import UserDatastore, UserModel

__all__ = ["UserDatastore", "UserModel"]
