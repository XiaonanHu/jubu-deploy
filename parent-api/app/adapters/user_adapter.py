"""
Adapter for user operations between the API and datastores.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from fastapi import HTTPException, status

from app_backend.app.api.security import verify_password, get_password_hash, create_access_token
from app_backend.app.core.config import settings
from app_backend.app.schemas.user import UserCreate, UserUpdate
from jubu_datastore import DatastoreFactory, User, UserDatastore

class UserAdapter:
    """Adapter for user operations."""
    
    def __init__(self):
        """Initialize the adapter with a user datastore."""
        self.user_datastore = DatastoreFactory.create_user_datastore()
    
    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate a user.
        
        Args:
            email: User email
            password: User password
            
        Returns:
            User entity if authentication succeeds, None otherwise
            
        Raises:
            HTTPException: If there's an error during authentication
        """
        try:
            # Find user by email
            user = self.user_datastore.get_by_email(email)
            
            # Check if user exists and password is correct
            if not user or not verify_password(password, user.hashed_password or ''):
                return None
            
            # Check if user is active
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Inactive user"
                )
            
            return user
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Authentication error: {str(e)}"
            )
    
    def get_or_create_demo_user(self, email: str) -> User:
        """
        For demo mode: return existing user by email, or create one with a fixed
        placeholder password. Password is ignored. Do not use in production.
        """
        user = self.user_datastore.get_by_email(email)
        if user:
            return user
        # Create user with placeholder password
        return self.user_datastore.create({
            "email": email,
            "full_name": email.split("@")[0] or "Demo User",
            "hashed_password": get_password_hash("demo"),
        })
    
    def create_user(self, user_data: UserCreate) -> User:
        """
        Create a new user.
        
        Args:
            user_data: User data
            
        Returns:
            Created user entity
            
        Raises:
            HTTPException: If there's an error creating the user
        """
        try:
            # User creation is handled by the datastore including duplicate checking
            user = self.user_datastore.create({
                'email': user_data.email,
                'full_name': user_data.full_name,
                'hashed_password': get_password_hash(user_data.password)
            })
            
            return user
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create user: {str(e)}"
            )
    
    def create_access_token_for_user(self, user: User) -> Dict[str, Any]:
        """
        Create an access token for a user.
        
        Args:
            user: User entity
            
        Returns:
            Access token information
        """
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.email},
            expires_delta=access_token_expires
        )
        
        return {"access_token": access_token, "token_type": "bearer"} 