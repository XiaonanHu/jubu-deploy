"""
Conversation management endpoints.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body

from app_backend.app.api import deps
from app_backend.app.api.security import get_current_active_user
from app_backend.app.schemas.conversation import (
    ConversationResponse,
    ConversationDetailResponse,
    ConversationTurnResponse,
    ConversationParentInsightsResponse,
)
from jubu_datastore import DatastoreFactory, User
from jubu_datastore.common.exceptions import ConversationDataError
from jubu_datastore.logging import get_logger
from app_backend.app.adapters.conversation_adapter import ConversationAdapter
from app_backend.app.adapters.profile_adapter import ProfileAdapter
from app_backend.app.adapters.user_adapter import UserAdapter

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=List[ConversationResponse])
async def get_conversations(
    limit: int = Query(5, ge=1, le=100),
    offset: int = Query(0, ge=0),
    child_id: Optional[str] = None,
    archived: bool = False,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Get conversations for a child.
    
    If child_id is not provided, returns conversations for all children of the current user.
    """
    logger.info(f"Getting conversations for user {current_user.id}, child_id={child_id}, archived={archived}")
    
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    logger.info(f"User {current_user.id} has profiles: {profile_ids}")
    
    # If child_id is provided, validate it belongs to the user
    if child_id and child_id not in profile_ids:
        logger.warning(f"Child ID {child_id} not found in profiles for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child profile not found"
        )
    
    # Get conversations
    conversation_adapter = ConversationAdapter(conversation_datastore)
    
    try:
        if child_id:
            # Get conversations for the specific child
            logger.info(f"Getting conversations for child {child_id}")
            conversations = conversation_adapter.get_conversations_by_child(
                child_id=child_id,
                limit=limit,
                offset=offset,
                archived=archived
            )
            logger.info(f"Found {len(conversations)} conversations for child {child_id}")
            return conversations
        else:
            # Get conversations for all children
            all_conversations = []
            for profile_id in profile_ids:
                logger.info(f"Getting conversations for child {profile_id}")
                conversations = conversation_adapter.get_conversations_by_child(
                    child_id=profile_id,
                    limit=limit,
                    offset=offset,
                    archived=archived
                )
                all_conversations.extend(conversations)
                logger.info(f"Found {len(conversations)} conversations for child {profile_id}")
            
            # Sort by last_interaction_time and apply limit/offset
            all_conversations.sort(
                key=lambda c: c.get("last_interaction_time", ""), 
                reverse=True
            )
            result = all_conversations[offset:offset + limit]
            logger.info(f"Returning {len(result)} conversations for all children")
            return result
    except Exception as e:
        logger.error(f"Error getting conversations: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving conversations: {str(e)}"
        )


@router.get("/stream", response_model=List[ConversationTurnResponse])
async def get_conversation_stream(
    child_id: str = Query(..., description="Child ID to get all turns for"),
    limit: Optional[int] = Query(None, ge=1, le=2000, description="Max turns to return (most recent); omit for all"),
    archived: bool = False,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore),
):
    """
    Get all turns for a child across all conversations, merged and sorted by timestamp.
    Frontend can render with dividers when conversation_id changes between consecutive turns.
    One request per poll for an instant child conversation view.
    """
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    if child_id not in profile_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child profile not found",
        )
    conversation_adapter = ConversationAdapter(conversation_datastore)
    turns = conversation_adapter.get_all_turns_for_child(
        child_id=child_id,
        archived=archived,
        limit=limit,
    )
    return turns


@router.get("/{conversation_id}/parent-insights", response_model=ConversationParentInsightsResponse)
async def get_conversation_parent_insights(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore),
):
    """
    Get parent-facing summary and suggestions for a conversation.
    Returns summary (string or null) and suggestions (list). Placeholder until summary generation is implemented.
    """
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]

    conversation_adapter = ConversationAdapter(conversation_datastore)
    try:
        conversation = conversation_adapter.get_conversation_detail(conversation_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve conversation",
        )

    if conversation.get("child_id") not in profile_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this conversation",
        )

    # Use fields if backend/datastore provides them; otherwise placeholder
    summary = conversation.get("parent_summary")
    suggestions = conversation.get("parent_suggestions") or []
    return ConversationParentInsightsResponse(summary=summary, suggestions=suggestions)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Get detailed information about a conversation, including messages.
    """
    # First get the user's profiles
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # Get the conversation
    conversation_adapter = ConversationAdapter(conversation_datastore)
    conversation = conversation_adapter.get_conversation_detail(conversation_id)
    
    # Check if the conversation belongs to one of the user's children
    if conversation["child_id"] not in profile_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this conversation"
        )
    
    return conversation


@router.post("/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Archive a conversation.
    """
    # First get the user's profiles
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # Check if the conversation exists and belongs to the user
    try:
        conversation_adapter = ConversationAdapter(conversation_datastore)
        conversation = conversation_adapter.get_conversation_detail(conversation_id)
        
        # Check if the conversation belongs to one of the user's children
        if conversation["child_id"] not in profile_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # Archive the conversation
        conversation_adapter.archive_conversation(conversation_id)
        
        return {"message": "Conversation archived successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error archiving conversation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to archive conversation: {str(e)}"
        )


@router.post("/{conversation_id}/delete")
async def delete_conversation_endpoint(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Delete an entire conversation.
    """
    logger.info(f"Deleting conversation {conversation_id}")
    
    # First get the user's profiles
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # Check if the conversation exists and belongs to the user
    try:
        conversation_adapter = ConversationAdapter(conversation_datastore)
        conversation = conversation_adapter.get_conversation_detail(conversation_id)
        
        # Check if the conversation belongs to one of the user's children
        if conversation["child_id"] not in profile_ids:
            logger.warning(f"User {current_user.id} tried to delete conversation {conversation_id} which does not belong to them")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # Delete the conversation
        conversation_datastore.hard_delete_conversation(conversation_id)
        
        return {"message": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting conversation: {str(e)}"
        )


@router.get("/statistics", response_model=dict)
async def get_conversation_statistics(
    child_id: Optional[str] = None,
    days: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Get statistics about conversations.
    """
    # First get the user's profiles to validate child_id
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # If child_id is provided, validate it belongs to the user
    if child_id and child_id not in profile_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Child profile not found"
        )
    
    # Get statistics
    conversation_adapter = ConversationAdapter(conversation_datastore)
    return conversation_adapter.get_conversation_statistics(
        child_id=child_id,
        days=days
    )


@router.get("/{conversation_id}/facts", response_model=Dict)
def get_conversation_facts(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get extracted facts from a conversation."""
    try:
        profile_datastore = DatastoreFactory.get_datastore("profile")
        conversation_datastore = DatastoreFactory.get_datastore("conversation")
        facts_datastore = DatastoreFactory.get_datastore("facts")
        
        # Get the conversation
        conversation = conversation_datastore.get(conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Check if the conversation belongs to one of the parent's children
        profiles = profile_datastore.get_profiles_by_parent(current_user.id)
        child_ids = [p.id for p in profiles]
        
        if conversation["child_id"] not in child_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # Get all turns from this conversation
        turns = conversation_datastore.get_conversation_history(conversation_id)
        turn_ids = [turn.get("id") for turn in turns]
        
        # Get facts extracted from these turns
        facts = []
        for turn_id in turn_ids:
            facts_from_turn = facts_datastore.get_facts_by_source_turn(turn_id)
            facts.extend(facts_from_turn)
        
        return {"facts": facts}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve conversation facts: {str(e)}"
        )


@router.delete("/{conversation_id}/turns")
async def delete_conversation_turns(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Delete all turns in a conversation.
    """
    # First get the user's profiles
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # Check if the conversation exists and belongs to the user
    try:
        conversation_adapter = ConversationAdapter(conversation_datastore)
        conversation = conversation_adapter.get_conversation_detail(conversation_id)
        
        # Check if the conversation belongs to one of the user's children
        if conversation["child_id"] not in profile_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # Delete the turns
        success = conversation_adapter.delete_conversation_turns(conversation_id)
        return {"message": "Conversation turns deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation turns: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete conversation turns: {str(e)}"
        )


@router.delete("/{conversation_id}/turns/{turn_id}")
async def delete_conversation_turn(
    conversation_id: str,
    turn_id: str,
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Delete a specific turn in a conversation.
    """
    # First get the user's profiles
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # Check if the conversation exists and belongs to the user
    try:
        conversation_adapter = ConversationAdapter(conversation_datastore)
        conversation = conversation_adapter.get_conversation_detail(conversation_id)
        
        # Check if the conversation belongs to one of the user's children
        if conversation["child_id"] not in profile_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # Delete the specific turn
        success = conversation_adapter.delete_conversation_turn(conversation_id, turn_id)
        return {"message": "Conversation turn deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation turn: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete conversation turn: {str(e)}"
        )


@router.delete("/{conversation_id}/selected-turns")
async def delete_selected_turns(
    conversation_id: str,
    turn_ids: List[str] = Body(..., embed=True),
    current_user: User = Depends(get_current_active_user),
    conversation_datastore = Depends(deps.get_conversation_datastore),
    profile_datastore = Depends(deps.get_profile_datastore)
):
    """
    Delete multiple selected turns from a conversation.
    """
    logger.info(f"Deleting selected turns {turn_ids} from conversation {conversation_id}")
    
    # First get the user's profiles
    profile_adapter = ProfileAdapter(profile_datastore)
    profiles = profile_adapter.get_profiles_by_parent(current_user.id)
    profile_ids = [p.id for p in profiles]
    
    # Check if the conversation exists and belongs to the user
    try:
        conversation_adapter = ConversationAdapter(conversation_datastore)
        conversation = conversation_adapter.get_conversation_detail(conversation_id)
        
        # Check if the conversation belongs to one of the user's children
        if conversation["child_id"] not in profile_ids:
            logger.warning(f"User {current_user.id} tried to delete turns from conversation {conversation_id} which does not belong to them")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # Delete the selected turns
        deleted_turns = []
        for turn_id in turn_ids:
            try:
                logger.info(f"Deleting turn {turn_id} from conversation {conversation_id}")
                conversation_adapter.delete_conversation_turn(conversation_id, turn_id)
                deleted_turns.append(turn_id)
            except HTTPException as e:
                logger.error(f"Error deleting turn {turn_id}: {str(e)}")
                # Continue with other turns if one fails
                continue
        
        if not deleted_turns:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No turns were deleted. Check if the turn IDs are valid."
            )
        
        # Return the updated conversation
        updated_conversation = conversation_adapter.get_conversation_detail(conversation_id)
        return updated_conversation
    except HTTPException:
        raise
    except ConversationDataError as e:
        logger.error(f"Error deleting turns: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation or turns not found: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error deleting turns: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting turns: {str(e)}"
        )