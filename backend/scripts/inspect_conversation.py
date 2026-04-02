#!/usr/bin/env python
"""
Script to inspect a specific conversation's turns, focusing on system_message fields.

Usage:
    python inspect_conversation.py <conversation_id>
"""

import json
import sqlite3
import sys

from jubu_chat.chat.datastores.conversation_datastore import (
    ConversationModel,
    ConversationTurnModel,
)
from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory


def inspect_conversation(conversation_id):
    """Inspect details of a specific conversation, focusing on message structure."""
    print(f"\nInspecting conversation: {conversation_id}")

    # Method 1: Use the datastore's get_conversation_history method
    conversation_datastore = DatastoreFactory.create_conversation_datastore()

    # Get basic conversation details within a session
    with conversation_datastore.session_scope() as session:
        conversation = (
            session.query(ConversationModel)
            .filter(ConversationModel.id == conversation_id)
            .first()
        )

        if not conversation:
            print(f"Conversation {conversation_id} not found!")
            return

        # Extract data while session is active
        print(f"\n== Conversation Details ==")
        print(f"Child ID: {conversation.child_id}")
        print(f"State: {conversation.state}")
        print(f"Metadata: {conversation.conv_metadata}")

    # Get turns via get_conversation_history
    print(f"\n== Turns via get_conversation_history ==")
    try:
        turns = conversation_datastore.get_conversation_history(conversation_id)
        print(f"Total turns: {len(turns)}")

        for i, turn in enumerate(turns, 1):
            print(f"\nTurn {i} (ID: {turn.get('id')})")
            print(f"Timestamp: {turn.get('timestamp')}")
            print(f"Interaction type: {turn.get('interaction_type')}")
            print(
                f"Child message: {turn.get('child_message')[:50]}..."
                if len(turn.get("child_message", "")) > 50
                else f"Child message: {turn.get('child_message')}"
            )

            # Check system_message field carefully
            system_message = turn.get("system_message")
            if system_message:
                print(f"System message exists: {True}")
                print(f"System message type: {type(system_message)}")
                print(f"System message length: {len(system_message)}")
                print(
                    f"System message preview: {system_message[:50]}..."
                    if len(system_message) > 50
                    else f"System message: {system_message}"
                )

                # Check if system_message might be JSON
                try:
                    if system_message.strip().startswith(
                        "{"
                    ) and system_message.strip().endswith("}"):
                        json_data = json.loads(system_message)
                        print(f"System message is valid JSON: {True}")
                        print(f"JSON keys: {list(json_data.keys())}")
                        if "response" in json_data:
                            print(
                                f"Response preview: {json_data['response'][:50]}..."
                                if len(json_data["response"]) > 50
                                else f"Response: {json_data['response']}"
                            )
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                print(f"System message is None or empty")
    except Exception as e:
        print(f"Error getting conversation history: {e}")

    # Method 2: Direct SQL query
    print(f"\n== Turns via direct SQL query ==")
    conn = sqlite3.connect("kidschat.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, timestamp, child_message, system_message, interaction_type 
        FROM conversation_turns 
        WHERE conversation_id = ?
        ORDER BY timestamp
    """,
        (conversation_id,),
    )
    sql_turns = cursor.fetchall()

    print(f"Total turns from SQL: {len(sql_turns)}")

    for i, (
        turn_id,
        timestamp,
        child_message,
        system_message,
        interaction_type,
    ) in enumerate(sql_turns, 1):
        print(f"\nTurn {i} (ID: {turn_id})")
        print(f"Timestamp: {timestamp}")
        print(f"Interaction type: {interaction_type}")
        print(
            f"Child message: {child_message[:50]}..."
            if len(child_message or "") > 50
            else f"Child message: {child_message}"
        )

        # Check system_message field carefully
        if system_message:
            print(f"System message exists: {True}")
            print(f"System message type: {type(system_message)}")
            print(f"System message length: {len(system_message)}")
            print(
                f"System message preview: {system_message[:50]}..."
                if len(system_message) > 50
                else f"System message: {system_message}"
            )

            # Check if system_message might be JSON
            try:
                if system_message.strip().startswith(
                    "{"
                ) and system_message.strip().endswith("}"):
                    json_data = json.loads(system_message)
                    print(f"System message is valid JSON: {True}")
                    print(f"JSON keys: {list(json_data.keys())}")
                    if "response" in json_data:
                        print(
                            f"Response preview: {json_data['response'][:50]}..."
                            if len(json_data["response"]) > 50
                            else f"Response: {json_data['response']}"
                        )
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            print(f"System message is None or empty")

    conn.close()


def main():
    if len(sys.argv) != 2:
        print("Usage: python inspect_conversation.py <conversation_id>")
        sys.exit(1)

    conversation_id = sys.argv[1]
    inspect_conversation(conversation_id)


if __name__ == "__main__":
    main()
