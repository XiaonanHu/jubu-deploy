"""
Dependency injection functions for the API.

These functions provide dependencies like datastores to API route handlers.
"""

from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app_backend.app.adapters.user_adapter import UserAdapter
from app_backend.app.api.security import get_current_user
from app_backend.app.core.config import settings
from jubu_datastore import (
    DatastoreFactory,
    ConversationDatastore,
    ProfileDatastore,
    FactsDatastore,
    UserDatastore,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def get_profile_datastore() -> ProfileDatastore:
    """
    Get a ProfileDatastore instance.
    
    Returns:
        An instance of ProfileDatastore
    """
    return DatastoreFactory.create_profile_datastore()


def get_conversation_datastore() -> ConversationDatastore:
    """
    Get a ConversationDatastore instance.
    
    Returns:
        An instance of ConversationDatastore
    """
    return DatastoreFactory.create_conversation_datastore()


def get_facts_datastore() -> FactsDatastore:
    """
    Get a FactsDatastore instance.
    
    Returns:
        An instance of FactsDatastore
    """
    return DatastoreFactory.create_facts_datastore()


def get_user_datastore() -> UserDatastore:
    """
    Get a UserDatastore instance.
    
    Returns:
        An instance of UserDatastore
    """
    return DatastoreFactory.create_user_datastore()


def get_user_adapter() -> UserAdapter:
    """
    Get a UserAdapter instance.
    
    Returns:
        An instance of UserAdapter
    """
    return UserAdapter()


# Other dependencies for specific operations, such as:

def get_user_profiles(
    profile_datastore: ProfileDatastore = Depends(get_profile_datastore),
    current_user = Depends(get_current_user)
):
    """
    Get all profiles for the current user.
    
    Args:
        profile_datastore: The profile datastore
        current_user: The current authenticated user
        
    Returns:
        A list of profiles for the current user
    """
    return profile_datastore.get_profiles_by_parent(current_user.id)