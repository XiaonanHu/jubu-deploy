"""
Authentication endpoints for the KidsChat Parent API.
"""

from datetime import timedelta
from typing import Annotated, List

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app_backend.app.adapters.user_adapter import UserAdapter
from app_backend.app.api import deps
from app_backend.app.core.config import settings
from jubu_datastore import User, UserDatastore
from jubu_datastore.logging import get_logger
from jubu_datastore.common.exceptions import UserDataError
from app_backend.app.schemas.token import Token
from app_backend.app.schemas.user import UserCreate, UserResponse

router = APIRouter()
logger = get_logger(__name__)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    user_in: UserCreate,
    user_adapter: UserAdapter = Depends(deps.get_user_adapter)
):
    """
    Register a new parent user.
    """
    try:
        # Create user using the adapter
        return user_adapter.create_user(user_in)
    except HTTPException as e:
        raise e
    except UserDataError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e) or "Email already registered",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/login", response_model=Token)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_adapter: UserAdapter = Depends(deps.get_user_adapter)
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    logger.info(f"Login attempt for user: {form_data.username}")
    if settings.DEMO_MODE:
        user = user_adapter.get_or_create_demo_user(form_data.username)
        logger.info(f"Demo mode: logged in as {user.email} (ID: {user.id})")
    else:
        user = user_adapter.authenticate_user(form_data.username, form_data.password)
        if not user:
            logger.warning(f"Authentication failed for user: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.info(f"Authentication successful for user: {user.email} (ID: {user.id})")
    token_response = user_adapter.create_access_token_for_user(user)
    logger.info(f"Generated token: {token_response['access_token'][:10]}...")
    return token_response


@router.post("/reset-password")
def reset_password(
    email: str = Body(..., embed=True),
    user_datastore: UserDatastore = Depends(deps.get_user_datastore)
):
    """
    Request password reset for a user.
    """
    # Check if user exists
    user = user_datastore.get_by_email(email)
    if not user:
        # Return success even if email doesn't exist (to prevent email enumeration)
        return {"message": "If your email is registered, you will receive a password reset link"}
    
    # TODO: Implement actual password reset email sending
    
    return {"message": "If your email is registered, you will receive a password reset link"}


# Only for development! Remove in production!
@router.get("/debug/users", response_model=List[UserResponse])
def debug_get_users(user_datastore: UserDatastore = Depends(deps.get_user_datastore)):
    """Get all users (for debugging only)."""
    try:
        return user_datastore.get_all_users()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve users: {str(e)}"
        )


# Debug endpoint to verify a token - remove in production
@router.get("/debug/verify-token")
async def debug_verify_token(current_user: User = Depends(deps.get_current_user)):
    """
    Debug endpoint to verify a token.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "verified": True
    }