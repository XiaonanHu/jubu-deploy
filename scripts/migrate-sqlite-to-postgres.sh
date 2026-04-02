#!/bin/bash
# ==========================================================
# Migrate data from local SQLite → cloud PostgreSQL
#
# Step 1: Run this locally to export data as JSON
# Step 2: Upload JSON files to VM
# Step 3: Run the import on the VM
# ==========================================================
set -e

SQLITE_DB="$HOME/Dev/jubu_backend/kidschat.db"
EXPORT_DIR="./migration-data"

mkdir -p "$EXPORT_DIR"

echo ""
echo "=========================================="
echo "  SQLite → PostgreSQL Migration"
echo "=========================================="
echo ""

echo "[1/2] Exporting data from SQLite..."

python3 << PYEOF
import sqlite3
import json
import os

db_path = os.path.expanduser("$SQLITE_DB")
export_dir = "$EXPORT_DIR"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all user tables
cursor.execute("""
    SELECT name FROM sqlite_master
    WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'alembic_%'
""")
tables = [row[0] for row in cursor.fetchall()]

print(f"  Found {len(tables)} tables: {', '.join(tables)}")
print()

for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]

    cursor.execute(f"SELECT * FROM {table}")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    output = {
        "table": table,
        "columns": columns,
        "rows": [list(row) for row in rows]
    }

    filepath = os.path.join(export_dir, f"{table}.json")
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"  {table}: {count} rows → {filepath}")

conn.close()
print()
print("  Export complete!")
PYEOF

echo ""
echo "[2/2] Upload and import..."
echo ""
echo "  Run these commands:"
echo ""
echo "  # Upload to VM:"
echo "  gcloud compute scp --recurse $EXPORT_DIR jubu-server:~/migration-data --zone=us-west1-b"
echo ""
echo "  # SSH into VM and import:"
echo "  gcloud compute ssh jubu-server --zone=us-west1-b"
echo "  cd ~/jubu-deploy"
echo "  docker compose exec backend python -c \""
echo "    import json, glob, os"
echo "    from sqlalchemy import create_engine, text"
echo "    engine = create_engine(os.environ['DATABASE_URI'])"
echo "    for f in sorted(glob.glob('/migration/*.json')):"
echo "        data = json.load(open(f))"
echo "        table = data['table']"
echo "        cols = data['columns']"
echo "        print(f'Importing {table}: {len(data[\"rows\"])} rows')"
echo "        with engine.begin() as conn:"
echo "            for row in data['rows']:"
echo "                placeholders = ', '.join([f':{c}' for c in cols])"
echo "                conn.execute(text(f'INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})'), dict(zip(cols, row)))"
echo "    print('Done!')"
echo "  \""
