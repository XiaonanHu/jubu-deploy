"""
Adapter for conversation operations between the API and KidsChat datastores.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import HTTPException, status

from jubu_datastore import ConversationDatastore
from jubu_datastore.common.exceptions import ConversationDataError
from app_backend.app.adapters.profile_adapter import ProfileAdapter

class ConversationAdapter:
    """Adapter for conversation operations."""
    
    def __init__(self, conversation_datastore: ConversationDatastore):
        """Initialize with a conversation datastore."""
        self.conversation_datastore = conversation_datastore
    
    def get_conversations_by_child(
        self, 
        child_id: str, 
        limit: int = 10, 
        offset: int = 0, 
        archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get conversations for a child.
        
        Args:
            child_id: The child ID
            limit: Maximum number of conversations to return
            offset: Offset for pagination
            archived: Whether to include archived conversations
            
        Returns:
            A list of conversations
            
        Raises:
            HTTPException: If there's an error retrieving conversations
        """
        try:
            # Get all conversations for the child
            conversations = self.conversation_datastore.get_conversations_by_child(child_id=child_id)
            
            # Filter by archived status
            if not archived:
                conversations = [c for c in conversations if not c.get('is_archived', False)]
            
            # Apply pagination
            total = len(conversations)
            conversations = conversations[offset:offset + limit]
            
            # Add pagination metadata
            for conv in conversations:
                conv['total_count'] = total
            
            return conversations
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve conversations: {str(e)}"
            )
    
    def get_conversation_detail(self, conversation_id: str) -> Dict[str, Any]:
        """
        Get details of a conversation.
        
        Args:
            conversation_id: The conversation ID
            
        Returns:
            Conversation details including turns
            
        Raises:
            HTTPException: If there's an error retrieving the conversation
        """
        try:
            conversation = self.conversation_datastore.get(conversation_id)
            if not conversation:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversation with ID {conversation_id} not found"
                )
            
            # Get turns for the conversation
            turns = self.conversation_datastore.get_conversation_history(conversation_id)
            
            # Add turns to the conversation
            conversation["turns"] = turns
            
            return conversation
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve conversation: {str(e)}"
            )
    
    def get_all_turns_for_child(
        self,
        child_id: str,
        archived: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all turns for a child across all their conversations, merged and sorted by timestamp ascending.
        Used for a single "stream" view with dividers when conversation_id changes.
        """
        try:
            conversations = self.conversation_datastore.get_conversations_by_child(child_id=child_id)
            if not archived:
                conversations = [c for c in conversations if not c.get("is_archived", False)]
            all_turns: List[Dict[str, Any]] = []
            for conv in conversations:
                cid = conv.get("id")
                if not cid:
                    continue
                turns = self.conversation_datastore.get_conversation_history(cid)
                for t in turns:
                    t["conversation_id"] = t.get("conversation_id") or cid
                    all_turns.append(t)
            all_turns.sort(key=lambda t: (t.get("timestamp") or datetime.min))
            if limit is not None and limit > 0:
                all_turns = all_turns[-limit:]
            return all_turns
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve turns for child: {str(e)}"
            )
    
    def archive_conversation(self, conversation_id: str) -> bool:
        """
        Archive a conversation.
        
        Args:
            conversation_id: The conversation ID
            
        Returns:
            True if archived, False otherwise
            
        Raises:
            HTTPException: If there's an error archiving the conversation
        """
        try:
            success = self.conversation_datastore.archive_conversation(conversation_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversation with ID {conversation_id} not found"
                )
            return True
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to archive conversation: {str(e)}"
            )
    
    def get_conversation_statistics(self, child_id: Optional[str] = None, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Get conversation statistics.
        
        Args:
            child_id: Filter by child ID (optional)
            days: Number of days to include (optional)
            
        Returns:
            Statistics about conversations
            
        Raises:
            HTTPException: If there's an error retrieving statistics
        """
        try:
            return self.conversation_datastore.get_conversation_statistics(
                child_id=child_id,
                days=days
            )
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve conversation statistics: {str(e)}"
            )
    
    def delete_conversation_turn(self, conversation_id: str, turn_id: str) -> bool:
        """
        Delete a specific turn in a conversation.
        
        Args:
            conversation_id: The conversation ID
            turn_id: The turn ID to delete
            
        Returns:
            True if deleted, False otherwise
            
        Raises:
            HTTPException: If there's an error deleting the turn
        """
        try:
            success = self.conversation_datastore.delete_turn(conversation_id, turn_id)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Turn with ID {turn_id} not found in conversation {conversation_id}"
                )
            return True
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete turn: {str(e)}"
            )
    
    def delete_conversation_turns(self, conversation_id: str) -> bool:
        """
        Delete all turns in a conversation.
        
        Args:
            conversation_id: The conversation ID
            
        Returns:
            True if deleted, False otherwise
            
        Raises:
            HTTPException: If there's an error deleting turns
        """
        try:
            # Get all turns for the conversation
            turns = self.conversation_datastore.get_conversation_history(conversation_id)
            if not turns:
                return True  # No turns to delete
            
            # Delete each turn
            for turn in turns:
                self.conversation_datastore.delete_turn(conversation_id, turn['id'])
                
            return True
        except ConversationDataError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete turns: {str(e)}"
            ) 