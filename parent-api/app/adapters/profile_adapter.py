"""
Adapter for profile operations between the API and KidsChat datastores.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import HTTPException, status
from pydantic import UUID4

from jubu_datastore import ProfileDatastore, ChildProfile
from jubu_datastore.common.exceptions import ProfileDataError
from app_backend.app.schemas.profile import ChildProfileCreate, ChildProfileUpdate

class ProfileAdapter:
    """Adapter for profile operations."""
    
    def __init__(self, profile_datastore: ProfileDatastore):
        """Initialize with a profile datastore."""
        self.profile_datastore = profile_datastore
    
    def get_profiles_by_parent(self, parent_id: str) -> List[ChildProfile]:
        """
        Get all profiles for a parent.
        
        Args:
            parent_id: The parent ID
            
        Returns:
            A list of child profile domain entities
            
        Raises:
            HTTPException: If there's an error retrieving profiles
        """
        try:
            return self.profile_datastore.get_profiles_by_parent(parent_id)
        except ProfileDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve profiles: {str(e)}"
            )
    
    def create_profile(self, parent_id: str, profile_data: ChildProfileCreate) -> ChildProfile:
        """
        Create a new child profile.
        
        Args:
            parent_id: The parent ID
            profile_data: The profile data
            
        Returns:
            The created profile domain entity
            
        Raises:
            HTTPException: If there's an error creating the profile
        """
        try:
            # Convert Pydantic model to dictionary and add parent_id
            data = profile_data.dict()
            data['parent_id'] = parent_id
            
            # Create the profile using the datastore
            profile = self.profile_datastore.create(data)
            return profile
        except ProfileDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create profile: {str(e)}"
            )
    
    def update_profile(self, profile_id: str, profile_data: ChildProfileUpdate) -> Optional[ChildProfile]:
        """
        Update a child profile.
        
        Args:
            profile_id: The profile ID
            profile_data: The profile data to update
            
        Returns:
            The updated profile entity or None if not found
            
        Raises:
            HTTPException: If there's an error updating the profile
        """
        try:
            # Convert Pydantic model to dictionary, excluding None values
            data = {k: v for k, v in profile_data.dict().items() if v is not None}
            
            # Update the profile using the datastore
            profile = self.profile_datastore.update(profile_id, data)
            if not profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Profile with ID {profile_id} not found"
                )
            return profile
        except ProfileDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update profile: {str(e)}"
            )
    
    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a child profile.
        
        Args:
            profile_id: The profile ID
            
        Returns:
            True if deleted, False otherwise
            
        Raises:
            HTTPException: If there's an error deleting the profile
        """
        try:
            success = self.profile_datastore.delete(profile_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Profile with ID {profile_id} not found"
                )
            return True
        except ProfileDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete profile: {str(e)}"
            )