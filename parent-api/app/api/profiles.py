"""
API endpoints for managing child profiles.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app_backend.app.adapters.profile_adapter import ProfileAdapter
from app_backend.app.api.deps import get_profile_datastore, get_current_user
from app_backend.app.core.config import settings
from app_backend.app.schemas.profile import ChildProfileCreate, ChildProfileUpdate, ChildProfileResponse
from app_backend.app.schemas.insight import ParentInsightPayloadSchema
from app_backend.app.services.insight_service import build_parent_insight_payload
from jubu_datastore import User

router = APIRouter()


def _ensure_demo_profile(profile_datastore, parent_id: str) -> None:
    """When DEMO_CHILD_ID (and optionally DEMO_PARENT_ID) are set, ensure the demo parent has that child. Never overwrite parent_id in demo mode."""
    if not settings.DEMO_CHILD_ID:
        return
    # In demo mode with fixed DEMO_PARENT_ID: only ensure the demo parent has the child; never create/update with another parent_id (do not overwrite DB).
    if settings.DEMO_MODE and settings.DEMO_PARENT_ID and parent_id != settings.DEMO_PARENT_ID:
        return
    existing_by_parent = profile_datastore.get_profiles_by_parent(parent_id)
    for p in existing_by_parent:
        if p.id == settings.DEMO_CHILD_ID:
            if getattr(p, "age", 3) < 3:
                profile_datastore.update(settings.DEMO_CHILD_ID, {"age": 3})
            return
    # Demo child not in this parent's list; create only for the intended demo parent (parent_id is already DEMO_PARENT_ID when we get here in demo mode)
    profile_datastore.create({
        "id": settings.DEMO_CHILD_ID,
        "name": "Demo Child",
        "age": 5,
        "parent_id": parent_id,
    })


@router.get("/", response_model=List[ChildProfileResponse])
def get_profiles(
    current_user: User = Depends(get_current_user),
    profile_datastore = Depends(get_profile_datastore)
):
    """
    Get all profiles for the current user.
    In demo mode with DEMO_PARENT_ID set, the current user is that parent; with DEMO_CHILD_ID set we ensure a demo child exists for them.
    """
    if settings.DEMO_MODE and settings.DEMO_CHILD_ID:
        _ensure_demo_profile(profile_datastore, current_user.id)
    adapter = ProfileAdapter(profile_datastore)
    return list(adapter.get_profiles_by_parent(current_user.id))

@router.post("/", response_model=ChildProfileResponse, status_code=status.HTTP_201_CREATED)
def create_profile(
    profile_in: ChildProfileCreate,
    current_user: User = Depends(get_current_user),
    profile_datastore = Depends(get_profile_datastore)
):
    """
    Create a new child profile.
    """
    adapter = ProfileAdapter(profile_datastore)
    return adapter.create_profile(current_user.id, profile_in)

@router.put("/{profile_id}", response_model=ChildProfileResponse)
def update_profile(
    profile_id: str,
    profile_in: ChildProfileUpdate,
    current_user: User = Depends(get_current_user),
    profile_datastore = Depends(get_profile_datastore)
):
    """
    Update a child profile.
    """
    adapter = ProfileAdapter(profile_datastore)
    # First check if the profile belongs to the current user
    profiles = adapter.get_profiles_by_parent(current_user.id)
    if not any(p.id == profile_id for p in profiles):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    return adapter.update_profile(profile_id, profile_in)

@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    profile_datastore = Depends(get_profile_datastore)
):
    """
    Delete a child profile.
    """
    adapter = ProfileAdapter(profile_datastore)
    # First check if the profile belongs to the current user
    profiles = adapter.get_profiles_by_parent(current_user.id)
    if not any(p.id == profile_id for p in profiles):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    adapter.delete_profile(profile_id)
    return None

@router.get("/{profile_id}/insights", response_model=ParentInsightPayloadSchema)
def get_profile_insights(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    profile_datastore = Depends(get_profile_datastore),
):
    """
    Get parent insight (discoveries / growth) for a child.
    Built from jubu_datastore only (CapabilityDatastore + CapabilityDefinitionRegistry).
    """
    adapter = ProfileAdapter(profile_datastore)
    profiles = adapter.get_profiles_by_parent(current_user.id)
    profile = next((p for p in profiles if p.id == profile_id), None)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    payload = build_parent_insight_payload(
        child_id=profile_id,
        child_name=profile.name,
        definition_root_path=None,
    )
    return payload


@router.get("/{profile_id}", response_model=ChildProfileResponse)
def get_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    profile_datastore = Depends(get_profile_datastore)
):
    """
    Get a specific child profile by ID.
    """
    adapter = ProfileAdapter(profile_datastore)
    # First check if the profile belongs to the current user
    profiles = adapter.get_profiles_by_parent(current_user.id)
    profile = next((p for p in profiles if p.id == profile_id), None)
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    return profile