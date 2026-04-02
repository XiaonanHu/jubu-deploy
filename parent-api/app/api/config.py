"""
Configuration endpoints for the KidsChat Parent API.
"""

from fastapi import APIRouter, Depends

from app_backend.app.adapters.config_adapter import ConfigAdapter
from app_backend.app.api.deps import get_current_user
from app_backend.app.core.config import settings
from jubu_datastore import User

router = APIRouter()


@router.get("/demo")
def get_demo_config(_: User = Depends(get_current_user)):
    """
    Return demo mode config for the app (demo_mode, demo_child_id).
    When DEMO_MODE is true and DEMO_CHILD_ID is set, the app can default to this child for conversations.
    """
    return {
        "demo_mode": settings.DEMO_MODE,
        "demo_child_id": settings.DEMO_CHILD_ID if settings.DEMO_MODE else None,
        "demo_parent_id": settings.DEMO_PARENT_ID if settings.DEMO_MODE else None,
    }


@router.get("/public")
def get_public_config():
    """
    Get public configuration settings.
    """
    adapter = ConfigAdapter()
    return adapter.get_public_config()

@router.get("/feature-flags")
def get_feature_flags(current_user = Depends(get_current_user)):
    """
    Get feature flags (requires authentication).
    """
    adapter = ConfigAdapter()
    return adapter.get_feature_flags()