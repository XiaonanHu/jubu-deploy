"""
User management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app_backend.app.api.security import get_current_active_user
from app_backend.app.schemas.user import UserResponse
from jubu_datastore import User

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user(current_user: User = Depends(get_current_active_user)):
    """
    Get details of the currently authenticated user.
    """
    return current_user 