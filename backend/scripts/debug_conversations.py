#!/usr/bin/env python
"""
Debug script for conversation turns in the database.

Usage:
    python debug_conversations.py [conversation_id]
"""

import sqlite3
import sys
import traceback
from datetime import datetime

from jubu_chat.chat.datastores.conversation_datastore import (
    ConversationModel,
    ConversationTurnModel,
)
from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory


def print_database_stats():
    """Print general statistics about the database tables."""
    conn = sqlite3.connect("kidschat.db")
    cursor = conn.cursor()

    # Get table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print(f"Database tables: {[t[0] for t in tables]}")

    # Get record counts for important tables
    for table in ["users", "child_profiles", "conversations", "conversation_turns"]:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table};")
            count = cursor.fetchone()[0]
            print(f"Table {table}: {count} records")
        except sqlite3.OperationalError:
            print(f"Table {table} does not exist")

    conn.close()


def show_conversation_details(conversation_id=None):
    """Show details about a specific conversation or all conversations."""
    # Create datastores
    conversation_datastore = DatastoreFactory.create_conversation_datastore()

    try:
        if conversation_id:
            # Get conversation details
            with conversation_datastore.session_scope() as session:
                conversation = (
                    session.query(ConversationModel)
                    .filter(ConversationModel.id == conversation_id)
                    .first()
                )

                if not conversation:
                    print(f"Conversation {conversation_id} not found!")
                    return

                print(f"\nConversation Details for {conversation_id}:")
                print(f"  Child ID: {conversation.child_id}")
                print(f"  State: {conversation.state}")
                print(f"  Start Time: {conversation.start_time}")
                print(f"  End Time: {conversation.end_time}")
                print(f"  Last Interaction: {conversation.last_interaction_time}")
                print(f"  Metadata: {conversation.conv_metadata}")
                print(f"  Is Archived: {conversation.is_archived}")

                # Get all turns using SQLAlchemy relationship
                print("\nTurns from relationship:")
                if hasattr(conversation, "turns"):
                    print(f"  Turn Count: {len(conversation.turns)}")
                    for i, turn in enumerate(conversation.turns, 1):
                        print(f"\nTurn {i} (ID: {turn.id}):")
                        print(f"  Timestamp: {turn.timestamp}")
                        print(f"  Type: {turn.interaction_type}")
                        print(
                            f"  Child: {turn.child_message[:50]}..."
                            if len(turn.child_message) > 50
                            else f"  Child: {turn.child_message}"
                        )
                        if turn.system_message:
                            print(
                                f"  AI: {turn.system_message[:50]}..."
                                if len(turn.system_message) > 50
                                else f"  AI: {turn.system_message}"
                            )
                else:
                    print("  No turns relationship found!")

                # Count turns directly
                turn_count = (
                    session.query(ConversationTurnModel)
                    .filter(ConversationTurnModel.conversation_id == conversation_id)
                    .count()
                )
                print(f"\nDirect SQL Turn Count: {turn_count}")

                # Get turns using get_conversation_history
                history_turns = conversation_datastore.get_conversation_history(
                    conversation_id
                )
                print(f"\nTurns from get_conversation_history: {len(history_turns)}")

                # Get actual turns from the database using SQL
                conn = sqlite3.connect("kidschat.db")
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    SELECT id, timestamp, child_message, system_message, interaction_type 
                    FROM conversation_turns 
                    WHERE conversation_id = ?
                    ORDER BY timestamp
                """,
                    (conversation_id,),
                )
                turns = cursor.fetchall()

                if turns:
                    print("\nConversation Turns from SQLite query:")
                    for i, turn in enumerate(turns, 1):
                        turn_id, timestamp, child_msg, system_msg, interaction = turn
                        print(f"\nTurn {i} (ID: {turn_id}):")
                        print(f"  Timestamp: {timestamp}")
                        print(f"  Type: {interaction}")
                        print(
                            f"  Child: {child_msg[:50]}..."
                            if len(child_msg) > 50
                            else f"  Child: {child_msg}"
                        )
                        if system_msg:
                            print(
                                f"  AI: {system_msg[:50]}..."
                                if len(system_msg) > 50
                                else f"  AI: {system_msg}"
                            )
                else:
                    print(
                        "\nNo turns found for this conversation in direct SQLite query!"
                    )

                conn.close()
        else:
            # List all conversations
            conversations = conversation_datastore.get_all_conversations()

            print(f"\nFound {len(conversations)} conversations:")
            for i, conv in enumerate(conversations, 1):
                print(f"{i}. ID: {conv['id']}")
                print(f"   Child ID: {conv['child_id']}")
                print(f"   State: {conv['state']}")
                print(f"   Start Time: {conv['start_time']}")
                print(f"   Turn Count: {conv.get('turn_count', 'Unknown')}")
                print()
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


def fix_conversation_turns():
    """Try to fix common issues with conversation turns."""
    conn = sqlite3.connect("kidschat.db")
    cursor = conn.cursor()

    # Check for conversations without turns
    cursor.execute(
        """
        SELECT c.id, c.child_id, c.state, 
               (SELECT COUNT(*) FROM conversation_turns t WHERE t.conversation_id = c.id) as turn_count 
        FROM conversations c
    """
    )
    conversations = cursor.fetchall()

    conversations_without_turns = [c for c in conversations if c[3] == 0]

    if conversations_without_turns:
        print(
            f"\nFound {len(conversations_without_turns)} conversations without turns:"
        )
        for conv in conversations_without_turns:
            print(f"  ID: {conv[0]}, Child ID: {conv[1]}, State: {conv[2]}")
    else:
        print("\nAll conversations have turns!")

    conn.close()


def main():
    """Main function."""
    print("KidsChat Database Debugger")
    print("==========================")

    print_database_stats()

    if len(sys.argv) > 1:
        conversation_id = sys.argv[1]
        show_conversation_details(conversation_id)
    else:
        show_conversation_details()

    fix_conversation_turns()


if __name__ == "__main__":
    main()
