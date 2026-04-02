#!/usr/bin/env python
"""
Fetch all conversations (and turns) for all children of the given parent.
Uses DEMO_PARENT_ID from the environment if no argument is given.

With --conversation <id>, print the full conversation (all turns, full messages) for that ID.

This mirrors what the parent app does: list my children → list conversations per child.

Usage:
    DEMO_PARENT_ID=<uuid> python scripts/get_conversations_by_parent_id.py
    python scripts/get_conversations_by_parent_id.py <parent_id>
    python scripts/get_conversations_by_parent_id.py --conversation <conversation_id>
    python scripts/get_conversations_by_parent_id.py --delete-empty-conversations [--child-id ID] [--dry-run]
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from jubu_chat.chat.datastores.datastore_factory import DatastoreFactory


def _strip_quotes(s):
    """Strip optional surrounding quotes from .env values."""
    if not s or not isinstance(s, str):
        return s
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        return s[1:-1]
    return s


def _print_full_conversation(conv_store, conversation_id: str) -> None:
    """Print the full conversation (all turns, full messages) for the given conversation ID."""
    conv = conv_store.get(conversation_id)
    if not conv:
        print(f"Conversation {conversation_id} not found.", file=sys.stderr)
        sys.exit(1)
    # conv may be a dict or an object
    cid = conv.get("id") if isinstance(conv, dict) else getattr(conv, "id", None)
    state = (
        conv.get("state") if isinstance(conv, dict) else getattr(conv, "state", None)
    )
    child_id = (
        conv.get("child_id")
        if isinstance(conv, dict)
        else getattr(conv, "child_id", None)
    )
    print(f"Conversation: {cid}")
    print(f"  child_id: {child_id}")
    print(f"  state: {state}")
    print()
    turns = conv_store.get_conversation_history(conversation_id)
    print(f"Turns: {len(turns)}")
    print("-" * 60)
    for i, t in enumerate(turns, 1):
        child_msg = t.get("child_message", "")
        system_msg = t.get("system_message", "") or ""
        safety = t.get("safety_evaluation") or {}
        print(f"Turn {i} (id={t.get('id', '')})")
        print(f"  child:  {child_msg}")
        print(
            f"  boojoo: {system_msg[:200] + '...' if len(system_msg) > 200 else system_msg}"
        )
        if safety:
            tags = safety.get("tags", [])
            redact = safety.get("redact_turn", False)
            if tags or redact:
                print(f"  safety: tags={tags} redact_turn={redact}")
        print()
    print("-" * 60)


def _print_all_conversations(conv_store) -> None:
    """Print all conversations in the datastore and count how many have parent_summary."""
    try:
        convs = conv_store.get_all_conversations()
    except AttributeError:
        print("Datastore does not support get_all_conversations().", file=sys.stderr)
        sys.exit(1)

    total = len(convs)
    with_summary = sum(
        1
        for c in convs
        if (
            c.get("parent_summary")
            if isinstance(c, dict)
            else getattr(c, "parent_summary", None)
        )
    )

    print("All conversations in datastore")
    print("=" * 60)
    print(f"Total: {total}")
    print(f"With parent_summary set: {with_summary}")
    print()

    for c in convs:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        child_id = (
            c.get("child_id") if isinstance(c, dict) else getattr(c, "child_id", None)
        )
        state = c.get("state") if isinstance(c, dict) else getattr(c, "state", None)
        ps = (
            c.get("parent_summary")
            if isinstance(c, dict)
            else getattr(c, "parent_summary", None)
        )
        has_summary = "yes" if (ps and str(ps).strip()) else "no"
        preview = ""
        if ps and str(ps).strip():
            s = str(ps).strip()
            preview = f" ({len(s)} chars, {s[:80]}...)" if len(s) > 80 else f" ({s})"
        print(
            f"  {cid}  child={child_id}  state={state}  parent_summary={has_summary}{preview}"
        )
    print()
    print(f"Summary: {with_summary} of {total} conversations have parent_summary set.")


def _delete_conversations_by_child(conv_store, child_id: str) -> None:
    """Hard-delete all conversations (and their turns) for the given child_id."""
    try:
        convs = conv_store.get_conversations_by_child(child_id)
    except AttributeError:
        convs = [
            c
            for c in conv_store.get_all_conversations()
            if c.get("child_id") == child_id
        ]

    total = len(convs)
    if total == 0:
        print(f"No conversations found for child_id={child_id}. Nothing to delete.")
        return

    print(f"Found {total} conversation(s) for child_id={child_id}.")
    confirm = input(
        f"Type 'yes' to permanently delete all {total} conversation(s) and their turns: "
    )
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    deleted = 0
    failed = 0
    for c in convs:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        try:
            if hasattr(conv_store, "hard_delete_conversation"):
                ok = conv_store.hard_delete_conversation(cid)
            else:
                ok = conv_store.delete(cid)
            if ok:
                deleted += 1
            else:
                failed += 1
                print(f"  Failed to delete {cid} (not found)", file=sys.stderr)
        except Exception as e:
            failed += 1
            print(f"  Error deleting {cid}: {e}", file=sys.stderr)

    print(f"Done. Deleted {deleted} conversation(s), {failed} failure(s).")


def _turn_count_for_conversation(conv_store, c) -> int:
    """Return turn count from conv dict if present, else count via history."""
    if isinstance(c, dict) and "turn_count" in c:
        return int(c.get("turn_count") or 0)
    cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
    if not cid:
        return 0
    try:
        return len(conv_store.get_conversation_history(cid))
    except Exception:
        return 0


def _collect_conversations_for_empty_prune(
    conv_store, child_id: Optional[str]
) -> List[Any]:
    """List conversation records (dicts with id) for optional child scope."""
    if child_id:
        try:
            return conv_store.get_conversations_by_child(child_id)
        except AttributeError:
            return [
                c
                for c in conv_store.get_all_conversations()
                if c.get("child_id") == child_id
            ]
    return conv_store.get_all_conversations()


def _delete_empty_turn_conversations(
    conv_store, child_id: Optional[str], *, dry_run: bool
) -> None:
    """
    Hard-delete conversations that have zero turns in the database.

    Uses turn_count from the datastore when available (efficient).
    """
    try:
        convs = _collect_conversations_for_empty_prune(conv_store, child_id)
    except AttributeError:
        print(
            "Datastore does not support listing conversations for empty-turn prune.",
            file=sys.stderr,
        )
        sys.exit(1)

    empty = [c for c in convs if _turn_count_for_conversation(conv_store, c) == 0]
    scope = f"child_id={child_id}" if child_id else "entire datastore"

    if not empty:
        print(f"No zero-turn conversations found ({scope}).")
        return

    print(f"Found {len(empty)} conversation(s) with 0 turns ({scope}).")
    for c in empty[:20]:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        print(f"  {cid}")
    if len(empty) > 20:
        print(f"  ... and {len(empty) - 20} more")

    if dry_run:
        print("Dry run: no deletions performed.")
        return

    confirm = input(
        f"Type 'yes' to permanently delete these {len(empty)} empty conversation(s): "
    )
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    deleted = 0
    failed = 0
    for c in empty:
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        try:
            if hasattr(conv_store, "hard_delete_conversation"):
                ok = conv_store.hard_delete_conversation(cid)
            else:
                ok = conv_store.delete(cid)
            if ok:
                deleted += 1
            else:
                failed += 1
                print(f"  Failed to delete {cid} (not found)", file=sys.stderr)
        except Exception as e:
            failed += 1
            print(f"  Error deleting {cid}: {e}", file=sys.stderr)

    print(f"Done. Deleted {deleted} empty conversation(s), {failed} failure(s).")


def main():
    parser = argparse.ArgumentParser(
        description="List conversations by parent ID, or print a full conversation by ID."
    )
    parser.add_argument(
        "parent_id",
        nargs="?",
        default=None,
        help="Parent ID (default: DEMO_PARENT_ID from env)",
    )
    parser.add_argument(
        "--conversation",
        "-c",
        metavar="ID",
        default=None,
        help="Print full conversation for this conversation ID (all turns, full messages).",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="List all conversations in the datastore (no parent_id). Print count with parent_summary.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Hard-delete all conversations for the given --child-id. Requires confirmation.",
    )
    parser.add_argument(
        "--child-id",
        metavar="ID",
        default=None,
        help="Child ID to use with --delete or --delete-empty-conversations.",
    )
    parser.add_argument(
        "--delete-empty-conversations",
        action="store_true",
        help=(
            "Hard-delete every conversation that has zero turns. "
            "Scope: all conversations, or only --child-id if set. "
            "Use --dry-run to list without deleting."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --delete-empty-conversations: list candidates only, do not delete.",
    )
    args = parser.parse_args()

    conv_store = DatastoreFactory.create_conversation_datastore()

    if args.delete_empty_conversations:
        child_id = _strip_quotes(args.child_id) if args.child_id else None
        _delete_empty_turn_conversations(conv_store, child_id, dry_run=args.dry_run)
        return

    if args.delete:
        child_id = _strip_quotes(args.child_id) if args.child_id else None
        if not child_id:
            print("--delete requires --child-id <id>", file=sys.stderr)
            sys.exit(1)
        _delete_conversations_by_child(conv_store, child_id)
        return

    if args.all:
        _print_all_conversations(conv_store)
        return

    if args.conversation:
        _print_full_conversation(conv_store, _strip_quotes(args.conversation))
        return

    raw = args.parent_id or os.getenv("DEMO_PARENT_ID")
    parent_id = _strip_quotes(raw) if raw else None
    if not parent_id:
        print(
            "Usage: DEMO_PARENT_ID=<id> python scripts/get_conversations_by_parent_id.py",
            file=sys.stderr,
        )
        print(
            "   or: python scripts/get_conversations_by_parent_id.py <parent_id>",
            file=sys.stderr,
        )
        print(
            "   or: python scripts/get_conversations_by_parent_id.py --all  (list all conversations, count parent_summary)",
            file=sys.stderr,
        )
        print(
            "   or: python scripts/get_conversations_by_parent_id.py --conversation <conversation_id>",
            file=sys.stderr,
        )
        sys.exit(1)

    profile_store = DatastoreFactory.create_profile_datastore()

    try:
        children = profile_store.get_profiles_by_parent(parent_id)
    except AttributeError:
        # Fallback: get all profiles and filter by parent_id (if no get_profiles_by_parent)
        all_profiles = getattr(profile_store, "get_all", lambda: [])()
        if not all_profiles and hasattr(profile_store, "session_scope"):
            children = []
        else:
            children = [
                p
                for p in (all_profiles if isinstance(all_profiles, list) else [])
                if getattr(p, "parent_id", None) == parent_id
            ]

    # Normalize to list of objects with .id and .name
    if not children:
        print(f"Parent ID: {parent_id}")
        print(
            "No children found for this parent (get_profiles_by_parent returned empty)."
        )
        print()
        print("Tip: The child profile's parent_id in the DB must match this value.")
        print(
            "  - Run: python scripts/show_demo_profile.py  (shows demo child's current parent_id)"
        )
        print(
            "  - If it differs, run: python scripts/attach_demo_parent_to_child.py  (sets child's parent_id from DEMO_PARENT_ID in .env)"
        )
        return

    print(f"Parent ID: {parent_id}")
    print(f"Children: {len(children)}")
    print()

    for child in children:
        child_id = child.id if hasattr(child, "id") else child.get("id")
        child_name = (
            getattr(child, "name", None)
            or (child.get("name") if isinstance(child, dict) else None)
            or "(no name)"
        )
        print(f"=== Child {child_id} ({child_name}) ===")

        try:
            convs = conv_store.get_conversations_by_child(child_id)
        except AttributeError:
            convs = [
                c
                for c in conv_store.get_all_conversations()
                if c.get("child_id") == child_id
            ]

        print(f"Conversations: {len(convs)}")
        with_summary = sum(1 for c in convs if c.get("parent_summary"))
        print(f"  With parent_summary set: {with_summary}")
        for c in convs:
            cid = c.get("id")
            ps = c.get("parent_summary")
            has_ps = "yes" if (ps and str(ps).strip()) else "no"
            print(
                f"  --- Conversation {cid} (state={c.get('state')}, parent_summary={has_ps}) ---"
            )
            if ps and str(ps).strip():
                preview = (
                    str(ps).strip()[:120] + "..." if len(str(ps)) > 120 else str(ps)
                )
                print(f"  parent_summary preview: {preview}")
            turns = conv_store.get_conversation_history(cid)
            print(f"  Turns: {len(turns)}")
            for i, t in enumerate(turns[:3], 1):
                msg = str(t.get("child_message", ""))[:50]
                print(f"    {i}. child: {msg}...")
            if len(turns) > 3:
                print(f"    ... and {len(turns) - 3} more turns")
        print()


if __name__ == "__main__":
    main()
