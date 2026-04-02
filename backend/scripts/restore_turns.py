#!/usr/bin/env python
"""
Script to check and restore conversation turns if they're missing.

Usage:
    python restore_turns.py <conversation_id>
"""

import json
import sqlite3
import sys
from datetime import datetime

from jubu_chat.chat.datastores.conversation_datastore import (
    ConversationModel,
    ConversationTurnModel,
)
from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory


def restore_conversation_turns(conversation_id):
    """Check if a conversation has turns and restore them if missing."""
    print(f"\nChecking conversation: {conversation_id}")

    # Create database connection
    conversation_datastore = DatastoreFactory.create_conversation_datastore()

    # Check if conversation exists
    with conversation_datastore.session_scope() as session:
        conversation = (
            session.query(ConversationModel)
            .filter(ConversationModel.id == conversation_id)
            .first()
        )

        if not conversation:
            print(f"Conversation {conversation_id} not found!")
            return

        # Check if the conversation has turns
        turn_count = (
            session.query(ConversationTurnModel)
            .filter(ConversationTurnModel.conversation_id == conversation_id)
            .count()
        )

        print(f"Current turn count: {turn_count}")

        if turn_count > 0:
            print("Conversation already has turns, no restoration needed.")
            return

        # If no turns, create sample turns for testing
        print("Conversation has no turns. Creating sample turns...")

        # Sample conversation structure
        sample_turns = [
            {
                "child_message": "hello",
                "system_message": "Hello! I'm Boojoo! It's great to meet you! Are you ready to have some fun?",
                "interaction_type": "chitchat",
                "timestamp": datetime.utcnow(),
                "safety_evaluation": {
                    "concerns": [],
                    "is_safe": True,
                    "severity": "low",
                },
            },
            {
                "child_message": "yes!",
                "system_message": "Yay! I'm so excited! What do you want to do first?",
                "interaction_type": "chitchat",
                "timestamp": datetime.utcnow(),
                "safety_evaluation": {
                    "concerns": [],
                    "is_safe": True,
                    "severity": "low",
                },
            },
            {
                "child_message": "let's play with sand",
                "system_message": "Sand is so much fun! Do you like to build sandcastles?",
                "interaction_type": "chitchat",
                "timestamp": datetime.utcnow(),
                "safety_evaluation": {
                    "concerns": [],
                    "is_safe": True,
                    "severity": "low",
                },
            },
        ]

        # Add the turns to the database
        for turn_data in sample_turns:
            # Add the conversation ID
            turn_data["conversation_id"] = conversation_id

            # Create the turn
            try:
                conversation_datastore.add_conversation_turn(conversation_id, turn_data)
                print(f"Added turn: {turn_data['child_message']}")
            except Exception as e:
                print(f"Error adding turn: {e}")

        # Verify the turns were added
        turn_count = (
            session.query(ConversationTurnModel)
            .filter(ConversationTurnModel.conversation_id == conversation_id)
            .count()
        )

        print(f"New turn count: {turn_count}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python restore_turns.py <conversation_id>")
        sys.exit(1)

    conversation_id = sys.argv[1]
    restore_conversation_turns(conversation_id)


if __name__ == "__main__":
    main()
