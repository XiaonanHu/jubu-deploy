#!/usr/bin/env python
"""
Fetch all conversations and turns for a child from the datastore.
Uses DEMO_CHILD_ID from the environment if no argument is given.

Usage:
    DEMO_CHILD_ID=<uuid> python scripts/get_turns_by_child_id.py
    python scripts/get_turns_by_child_id.py <child_id>
"""

import json
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory


def main():
    child_id = (sys.argv[1] if len(sys.argv) > 1 else None) or os.getenv(
        "DEMO_CHILD_ID"
    )
    if not child_id:
        print("Usage: DEMO_CHILD_ID=<id> python scripts/get_turns_by_child_id.py")
        print(
            "   or: python scripts/get_turns_by_child_id.py <child_id>", file=sys.stderr
        )
        sys.exit(1)

    store = DatastoreFactory.create_conversation_datastore()

    # Get conversations for this child (try get_conversations_by_child first)
    try:
        convs = store.get_conversations_by_child(child_id)
    except AttributeError:
        convs = [
            c for c in store.get_all_conversations() if c.get("child_id") == child_id
        ]

    print(f"Child ID: {child_id}")
    print(f"Conversations: {len(convs)}")
    print()

    for c in convs:
        cid = c.get("id")
        print(f"--- Conversation {cid} (state={c.get('state')}) ---")
        turns = store.get_conversation_history(cid)
        print(f"Turns: {len(turns)}")
        for i, t in enumerate(turns, 1):
            print(
                f"  {i}. [{t.get('timestamp')}] child: {str(t.get('child_message', ''))[:60]}..."
            )
            print(f"     system: {str(t.get('system_message', ''))[:60]}...")
        print()

    if not convs:
        print("No conversations found for this child_id.")


if __name__ == "__main__":
    main()
