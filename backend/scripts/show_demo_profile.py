#!/usr/bin/env python
"""
Show the demo child profile from the datastore (id, name, age, parent_id, etc.).
Uses DEMO_CHILD_ID from the environment if no argument is given.

Use this to see whether the demo child is linked to a parent for the parent app demo.

Usage:
    DEMO_CHILD_ID=<uuid> python scripts/show_demo_profile.py
    python scripts/show_demo_profile.py <child_id>
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory


def main():
    child_id = (sys.argv[1] if len(sys.argv) > 1 else None) or os.getenv(
        "DEMO_CHILD_ID"
    )
    if not child_id:
        print(
            "Usage: DEMO_CHILD_ID=<id> python scripts/show_demo_profile.py",
            file=sys.stderr,
        )
        print("   or: python scripts/show_demo_profile.py <child_id>", file=sys.stderr)
        sys.exit(1)

    profile_store = DatastoreFactory.create_profile_datastore()
    profile = profile_store.get(child_id)

    print(f"Child ID: {child_id}")
    if not profile:
        print("Profile: NOT FOUND in datastore.")
        print(
            "Create it (e.g. via parent app seed or text_chat --write-to-datastore once)."
        )
        return

    # Support both Pydantic-style and dict-style
    if hasattr(profile, "model_dump"):
        d = profile.model_dump()
    elif hasattr(profile, "dict"):
        d = profile.dict()
    else:
        d = (
            dict(profile)
            if hasattr(profile, "__iter__")
            else {"id": getattr(profile, "id", None)}
        )

    parent_id = d.get("parent_id") or getattr(profile, "parent_id", None)
    print(f"Profile found:")
    print(f"  id:          {d.get('id', getattr(profile, 'id', None))}")
    print(f"  name:        {d.get('name', getattr(profile, 'name', None))}")
    print(f"  age:         {d.get('age', getattr(profile, 'age', None))}")
    print(f"  parent_id:   {parent_id}")
    print(f"  interests:   {d.get('interests', getattr(profile, 'interests', None))}")
    print()
    if parent_id:
        print(
            "For parent app demo: set DEMO_PARENT_ID to the value above so the parent app"
        )
        print(
            "shows this child under that parent. Ensure a User exists with id = DEMO_PARENT_ID."
        )
    else:
        print("parent_id is not set. For the demo, either:")
        print(
            "  1. Set parent_id on this profile to your demo parent's user id (DEMO_PARENT_ID),"
        )
        print(
            "  2. Or in the parent app use a demo user whose id you then set here as parent_id."
        )


if __name__ == "__main__":
    main()
