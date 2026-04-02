"""
Conversation datastore for KidsChat.

This module provides storage and retrieval functionality for conversations,
ensuring proper data security, privacy, and compliance with data protection regulations.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from jubu_datastore.base_datastore import BaseDatastore
from jubu_datastore.common.constants import DEFAULT_ARCHIVE_DAYS
from jubu_datastore.common.enums import ConversationState
from jubu_datastore.common.exceptions import ConversationDataError
from jubu_datastore.logging import get_logger

logger = get_logger(__name__)


class ConversationModel(BaseDatastore.Base):
    """SQLAlchemy model for conversations."""

    __tablename__ = "conversations"

    id = sa.Column(sa.String(36), primary_key=True)
    child_id = sa.Column(sa.String(36), nullable=False, index=True)
    state = sa.Column(sa.String(20), nullable=False, index=True)
    start_time = sa.Column(
        sa.DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    end_time = sa.Column(sa.DateTime, nullable=True)
    last_interaction_time = sa.Column(
        sa.DateTime, nullable=False, default=datetime.utcnow
    )
    conv_metadata = sa.Column(sa.JSON, nullable=True)
    is_archived = sa.Column(sa.Boolean, nullable=False, default=False, index=True)
    parent_summary = sa.Column(sa.Text, nullable=True)

    turns = relationship(
        "ConversationTurnModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.Index("idx_child_state_time", child_id, state, start_time),
        sa.Index("idx_archived_time", is_archived, start_time),
    )


class ConversationTurnModel(BaseDatastore.Base):
    """SQLAlchemy model for conversation turns."""

    __tablename__ = "conversation_turns"

    id = sa.Column(sa.String(36), primary_key=True)
    conversation_id = sa.Column(
        sa.String(36), sa.ForeignKey("conversations.id"), nullable=False, index=True
    )
    timestamp = sa.Column(
        sa.DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    child_message = sa.Column(sa.Text, nullable=False)
    system_message = sa.Column(sa.Text, nullable=True)
    interaction_type = sa.Column(sa.String(50), nullable=False)
    safety_evaluation = sa.Column(sa.JSON, nullable=True)

    conversation = relationship("ConversationModel", back_populates="turns")

    __table_args__ = (sa.Index("idx_conversation_time", conversation_id, timestamp),)


class ConversationDatastore(BaseDatastore):
    """
    Datastore for managing conversation data.

    This class handles storage, retrieval, and management of conversations
    and conversation turns, with proper security and privacy measures.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        pool_size: Optional[int] = None,
        encryption_key: Optional[str] = None,
    ):
        super().__init__(
            connection_string=connection_string,
            pool_size=pool_size,
            encryption_key=encryption_key,
            model_class=ConversationModel,
        )

        self.Base.metadata.create_all(self.engine)

    def create(self, data: Dict[str, Any]) -> ConversationModel:
        return self.save_conversation(data)

    def get(self, record_id: str) -> Optional[Dict[str, Any]]:
        with self.session_scope() as session:
            conversation = (
                session.query(ConversationModel)
                .filter(ConversationModel.id == record_id)
                .first()
            )
            if not conversation:
                return None

            conversation_dict = {
                "id": conversation.id,
                "child_id": conversation.child_id,
                "state": conversation.state,
                "start_time": conversation.start_time,
                "end_time": conversation.end_time,
                "last_interaction_time": conversation.last_interaction_time,
                "conv_metadata": conversation.conv_metadata,
                "is_archived": conversation.is_archived,
                "parent_summary": conversation.parent_summary,
            }

            return conversation_dict

    def update(
        self, record_id: str, data: Dict[str, Any]
    ) -> Optional[ConversationModel]:
        with self.session_scope() as session:
            conversation = (
                session.query(ConversationModel)
                .filter(ConversationModel.id == record_id)
                .first()
            )
            if not conversation:
                return None

            for key, value in data.items():
                if hasattr(conversation, key):
                    setattr(conversation, key, value)

            conversation.last_interaction_time = datetime.utcnow()

            session.commit()
            return conversation

    def delete(self, record_id: str) -> bool:
        return self.delete_conversation(record_id)

    def save_conversation(self, conversation_data: Dict[str, Any]) -> ConversationModel:
        """
        Create a new conversation.

        Args:
            conversation_data: Dictionary containing conversation data

        Returns:
            Created conversation record

        Raises:
            ConversationDataError: If required fields are missing
        """
        try:
            required_fields = ["child_id"]
            for field in required_fields:
                if field not in conversation_data:
                    raise ConversationDataError(f"Missing required field: {field}")

            conversation_id = conversation_data.get("id", str(uuid.uuid4()))

            conversation = ConversationModel(
                id=conversation_id,
                child_id=conversation_data["child_id"],
                state=conversation_data.get("state", ConversationState.ACTIVE.value),
                start_time=conversation_data.get("start_time", datetime.utcnow()),
                conv_metadata=conversation_data.get("conv_metadata", {}),
                parent_summary=conversation_data.get("parent_summary"),
            )

            with self.session_scope() as session:
                session.add(conversation)
                session.commit()
                logger.info(
                    f"Created conversation {conversation_id} for child {conversation_data['child_id']}"
                )
                return conversation
        except Exception as e:
            logger.error(f"Error saving conversation: {e}")
            raise ConversationDataError(f"Failed to save conversation: {str(e)}")

    def update_conversation_state(
        self, conversation_id: str, state: Union[str, ConversationState]
    ) -> bool:
        try:
            if isinstance(state, ConversationState):
                state = state.value

            with self.session_scope() as session:
                conversation = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .first()
                )
                if not conversation:
                    logger.warning(f"Conversation {conversation_id} not found")
                    return False

                conversation.state = state
                conversation.last_interaction_time = datetime.utcnow()

                if state in [
                    ConversationState.ENDED.value,
                    ConversationState.FLAGGED.value,
                ]:
                    conversation.end_time = datetime.utcnow()

                session.commit()
                logger.info(f"Updated conversation {conversation_id} state to {state}")
                return True
        except Exception as e:
            logger.error(f"Error updating conversation state: {e}")
            raise ConversationDataError(
                f"Failed to update conversation state: {str(e)}"
            )

    def set_conversation_parent_summary(
        self, conversation_id: str, summary: str
    ) -> bool:
        """
        Save the parent-facing summary for a conversation (e.g. after backend generates it).

        Args:
            conversation_id: ID of the conversation
            summary: Summary text for the parent

        Returns:
            True if the conversation was found and updated, False otherwise
        """
        updated = self.update(conversation_id, {"parent_summary": summary})
        return updated is not None

    def add_conversation_turn(
        self, conversation_id: str, turn_data: Dict[str, Any]
    ) -> ConversationTurnModel:
        """
        Add a new turn to a conversation.

        Args:
            conversation_id: ID of the conversation
            turn_data: Dictionary containing turn data

        Returns:
            Created turn record

        Raises:
            ConversationDataError: If conversation not found or required fields missing
        """
        try:
            required_fields = ["child_message", "interaction_type"]
            for field in required_fields:
                if field not in turn_data:
                    raise ConversationDataError(f"Missing required field: {field}")

            turn_id = turn_data.get("id", str(uuid.uuid4()))

            with self.session_scope() as session:
                conversation = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .first()
                )
                if not conversation:
                    raise ConversationDataError(
                        f"Conversation {conversation_id} not found"
                    )

                turn = ConversationTurnModel(
                    id=turn_id,
                    conversation_id=conversation_id,
                    timestamp=turn_data.get("timestamp", datetime.utcnow()),
                    child_message=turn_data["child_message"],
                    system_message=turn_data.get("system_message"),
                    interaction_type=turn_data["interaction_type"],
                    safety_evaluation=turn_data.get("safety_evaluation"),
                )

                session.add(turn)

                conversation.last_interaction_time = turn.timestamp

                session.commit()
                logger.debug(f"Added turn {turn_id} to conversation {conversation_id}")
                return turn
        except Exception as e:
            logger.error(f"Error adding conversation turn: {e}")
            raise ConversationDataError(f"Failed to add conversation turn: {str(e)}")

    def update_conversation_turn(
        self,
        conversation_id: str,
        turn_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Update an existing conversation turn (e.g. after safety evaluation).

        Used by the streaming path to persist safety_evaluation and redacted
        child_message so the parent app can read them from the DB.
        """
        allowed = {"safety_evaluation", "child_message"}
        updates = {k: v for k, v in updates.items() if k in allowed}
        if not updates:
            return True
        try:
            with self.session_scope() as session:
                turn = (
                    session.query(ConversationTurnModel)
                    .filter(
                        ConversationTurnModel.id == turn_id,
                        ConversationTurnModel.conversation_id == conversation_id,
                    )
                    .first()
                )
                if not turn:
                    logger.warning(
                        "update_conversation_turn: turn %s not found in conv %s",
                        turn_id,
                        conversation_id,
                    )
                    return False
                for key, value in updates.items():
                    if hasattr(turn, key):
                        setattr(turn, key, value)
                session.commit()
                logger.debug(
                    "Updated turn %s in conversation %s with keys %s",
                    turn_id,
                    conversation_id,
                    list(updates.keys()),
                )
                return True
        except Exception as e:
            logger.error(f"Error updating conversation turn: {e}")
            return False

    def get_conversation_history(
        self, conversation_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the history of a conversation.

        Args:
            conversation_id: ID of the conversation
            limit: Maximum number of turns to retrieve (most recent first)

        Returns:
            List of conversation turns

        Raises:
            ConversationDataError: If conversation not found
        """
        try:
            with self.session_scope() as session:
                conversation = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .first()
                )
                if not conversation:
                    raise ConversationDataError(
                        f"Conversation {conversation_id} not found"
                    )

                query = (
                    session.query(ConversationTurnModel)
                    .filter(ConversationTurnModel.conversation_id == conversation_id)
                    .order_by(ConversationTurnModel.timestamp.desc())
                )

                if limit:
                    query = query.limit(limit)

                turns = query.all()

                result = []
                for turn in turns:
                    turn_dict = {
                        "id": turn.id,
                        "conversation_id": turn.conversation_id,
                        "timestamp": turn.timestamp,
                        "child_message": turn.child_message,
                        "system_message": turn.system_message,
                        "interaction_type": turn.interaction_type,
                        "safety_evaluation": turn.safety_evaluation,
                    }
                    result.append(turn_dict)

                result.reverse()

                return result
        except Exception as e:
            logger.error(f"Error retrieving conversation history: {e}")
            raise ConversationDataError(
                f"Failed to retrieve conversation history: {str(e)}"
            )

    def get_conversations_by_child(
        self, child_id: str, state: Optional[Union[str, ConversationState]] = None
    ) -> List[Dict[str, Any]]:
        try:
            with self.session_scope() as session:
                query = session.query(ConversationModel).filter(
                    ConversationModel.child_id == child_id
                )

                if state:
                    state_value = (
                        state.value if isinstance(state, ConversationState) else state
                    )
                    query = query.filter(ConversationModel.state == state_value)

                query = query.order_by(ConversationModel.last_interaction_time.desc())

                conversations = query.all()

                result = []
                for conv in conversations:
                    conv_dict = {
                        "id": conv.id,
                        "child_id": conv.child_id,
                        "state": conv.state,
                        "start_time": conv.start_time,
                        "end_time": conv.end_time,
                        "last_interaction_time": conv.last_interaction_time,
                        "conv_metadata": conv.conv_metadata,
                        "is_archived": conv.is_archived,
                        "parent_summary": conv.parent_summary,
                        "turn_count": session.query(ConversationTurnModel)
                        .filter(ConversationTurnModel.conversation_id == conv.id)
                        .count(),
                    }
                    result.append(conv_dict)

                return result
        except Exception as e:
            logger.error(f"Error retrieving conversations for child {child_id}: {e}")
            raise ConversationDataError(f"Failed to retrieve conversations: {str(e)}")

    def delete_conversation(self, conversation_id: str) -> bool:
        """Safely delete a conversation (GDPR compliance) via soft delete."""
        try:
            with self.session_scope() as session:
                update_result = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .update(
                        {
                            "is_archived": True,
                            "state": ConversationState.ENDED.value,
                            "end_time": datetime.utcnow(),
                        }
                    )
                )

                if update_result == 0:
                    logger.warning(
                        f"Conversation {conversation_id} not found for deletion"
                    )
                    return False

                session.commit()
                logger.info(f"Soft-deleted conversation {conversation_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            raise ConversationDataError(f"Failed to delete conversation: {str(e)}")

    def hard_delete_conversation(self, conversation_id: str) -> bool:
        """Permanently delete a conversation and all its turns."""
        try:
            with self.session_scope() as session:
                conversation = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .first()
                )
                if not conversation:
                    logger.warning(
                        f"Conversation {conversation_id} not found for hard deletion"
                    )
                    return False

                session.delete(conversation)
                session.commit()
                logger.info(f"Hard-deleted conversation {conversation_id}")
                return True
        except Exception as e:
            logger.error(f"Error hard-deleting conversation: {e}")
            raise ConversationDataError(f"Failed to hard-delete conversation: {str(e)}")

    def archive_old_conversations(
        self, days_threshold: int = DEFAULT_ARCHIVE_DAYS
    ) -> int:
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)

            with self.session_scope() as session:
                conversations = (
                    session.query(ConversationModel)
                    .filter(
                        ConversationModel.last_interaction_time < cutoff_date,
                        ConversationModel.is_archived == False,
                    )
                    .all()
                )

                count = 0
                for conversation in conversations:
                    conversation.is_archived = True
                    count += 1

                session.commit()
                logger.info(
                    f"Archived {count} conversations older than {days_threshold} days"
                )
                return count
        except Exception as e:
            logger.error(f"Error archiving old conversations: {e}")
            raise ConversationDataError(
                f"Failed to archive old conversations: {str(e)}"
            )

    def archive_conversation(self, conversation_id: str) -> bool:
        updated = self.update(conversation_id, {"is_archived": True})
        return updated is not None

    def get_conversation_statistics(
        self, child_id: Optional[str] = None, days: Optional[int] = None
    ) -> Dict[str, Any]:
        try:
            with self.session_scope() as session:
                query = session.query(ConversationModel)

                if child_id:
                    query = query.filter(ConversationModel.child_id == child_id)

                if days:
                    cutoff_date = datetime.utcnow() - timedelta(days=days)
                    query = query.filter(ConversationModel.start_time >= cutoff_date)

                state_counts = {}
                for state in ConversationState:
                    count = query.filter(ConversationModel.state == state.value).count()
                    state_counts[state.value] = count

                total_count = query.count()

                avg_turns = (
                    session.query(
                        func.avg(
                            session.query(ConversationTurnModel)
                            .filter(
                                ConversationTurnModel.conversation_id
                                == ConversationModel.id
                            )
                            .correlate(ConversationModel)
                            .statement.with_only_columns([func.count()])
                        )
                    ).scalar()
                    or 0
                )

                return {
                    "total_conversations": total_count,
                    "state_counts": state_counts,
                    "average_turns_per_conversation": float(avg_turns),
                    "filter_child_id": child_id,
                    "filter_days": days,
                }
        except Exception as e:
            logger.error(f"Error getting conversation statistics: {e}")
            raise ConversationDataError(
                f"Failed to get conversation statistics: {str(e)}"
            )

    def get_all_conversations(self) -> List[Dict[str, Any]]:
        try:
            with self.session_scope() as session:
                conversations = (
                    session.query(ConversationModel)
                    .order_by(ConversationModel.last_interaction_time.desc())
                    .all()
                )

                result = []
                for conv in conversations:
                    turn_count = (
                        session.query(ConversationTurnModel)
                        .filter(ConversationTurnModel.conversation_id == conv.id)
                        .count()
                    )

                    conv_dict = {
                        "id": conv.id,
                        "child_id": conv.child_id,
                        "state": conv.state,
                        "start_time": conv.start_time,
                        "end_time": conv.end_time,
                        "last_interaction_time": conv.last_interaction_time,
                        "conv_metadata": conv.conv_metadata,
                        "is_archived": conv.is_archived,
                        "parent_summary": conv.parent_summary,
                        "turn_count": turn_count,
                    }
                    result.append(conv_dict)

                return result
        except Exception as e:
            logger.error(f"Error retrieving all conversations: {e}")
            raise ConversationDataError(f"Failed to retrieve conversations: {str(e)}")

    def delete_turn(self, conversation_id: str, turn_id: str) -> bool:
        try:
            with self.session_scope() as session:
                conversation = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .first()
                )

                if not conversation:
                    logger.warning(
                        f"Conversation {conversation_id} not found for turn deletion"
                    )
                    return False

                turn = (
                    session.query(ConversationTurnModel)
                    .filter(
                        ConversationTurnModel.id == turn_id,
                        ConversationTurnModel.conversation_id == conversation_id,
                    )
                    .first()
                )

                if not turn:
                    logger.warning(
                        f"Turn {turn_id} not found in conversation {conversation_id}"
                    )
                    return False

                session.delete(turn)
                session.commit()
                logger.info(
                    f"Deleted turn {turn_id} from conversation {conversation_id}"
                )
                return True
        except Exception as e:
            logger.error(f"Error deleting conversation turn: {e}")
            raise ConversationDataError(f"Failed to delete conversation turn: {str(e)}")
