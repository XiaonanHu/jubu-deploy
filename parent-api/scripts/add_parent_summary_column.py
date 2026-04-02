"""
Add missing parent_summary column to conversations table.

Use this when you see: sqlite3.OperationalError: no such column: conversations.parent_summary

The jubu_datastore Conversation model expects this column; the DB may have been
created before it was added. Run from repo root so .env is loaded:

  python -m app_backend.scripts.add_parent_summary_column

Idempotent: safe to run multiple times (skips if column already exists).
"""

from __future__ import annotations

import os
import sys

# Ensure repo root is on path so app_backend and .env are found
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
os.chdir(_REPO_ROOT)

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app_backend.app.core.config import settings


def main() -> None:
    url = os.environ.get("DATABASE_URL") or settings.DATABASE_URI
    engine = create_engine(url)
    table_name = "conversations"
    column_name = "parent_summary"

    with engine.connect() as conn:
        try:
            cur = conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"
                ),
                {"t": table_name},
            )
            if cur.fetchone() is None:
                print(f"Table {table_name} does not exist; skipping.")
                return
        except OperationalError:
            conn.rollback()
            print(f"Table {table_name} not accessible; skipping.")
            return

        try:
            cur = conn.execute(
                text(
                    f"SELECT 1 FROM pragma_table_info('{table_name}') WHERE name = '{column_name}'"
                )
            )
            if cur.fetchone() is not None:
                print(f"Column {table_name}.{column_name} already exists; skipping.")
                return
        except OperationalError:
            conn.rollback()

        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT"))
        conn.commit()
        print(f"Added column {table_name}.{column_name}.")


if __name__ == "__main__":
    main()
