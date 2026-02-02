#!/usr/bin/env python3
"""
Optional standalone migration: add public_endpoint, lighthouse_options, first_polled_at to nodes;
ensure enrollment_codes table exists. The backend runs the same migrations automatically at
startup (database._run_sqlite_migrations). Use this script only when you need to migrate
without starting the API (e.g. one-off from CLI).
Run from repo root: python -m backend.scripts.migrate_nodes_columns
Or with database_url: NEBULA_COMMANDER_DATABASE_URL=... python -m backend.scripts.migrate_nodes_columns
"""
import os
import sqlite3
import sys

# Default SQLite path used by app
DEFAULT_DB = os.environ.get(
    "NEBULA_COMMANDER_DATABASE_PATH",
    os.environ.get(
        "DATABASE_PATH",
        "/var/lib/nebula-commander/db.sqlite",
    ),
)

# If database_url is set (e.g. sqlite+aiosqlite:////var/lib/... for absolute path), extract path
DATABASE_URL = os.environ.get("NEBULA_COMMANDER_DATABASE_URL", "")
if DATABASE_URL and DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.split("///")[-1].split("?")[0]
else:
    db_path = DEFAULT_DB


def main() -> int:
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(nodes)")
    columns = {row[1] for row in cur.fetchall()}
    if "public_endpoint" not in columns:
        cur.execute("ALTER TABLE nodes ADD COLUMN public_endpoint VARCHAR(512)")
        print("Added column: public_endpoint")
    else:
        print("Column public_endpoint already exists")
    if "lighthouse_options" not in columns:
        cur.execute("ALTER TABLE nodes ADD COLUMN lighthouse_options TEXT")
        print("Added column: lighthouse_options")
    else:
        print("Column lighthouse_options already exists")
    if "first_polled_at" not in columns:
        cur.execute("ALTER TABLE nodes ADD COLUMN first_polled_at DATETIME")
        print("Added column: first_polled_at")
    else:
        print("Column first_polled_at already exists")

    # enrollment_codes table (for dnclient-style enrollment)
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='enrollment_codes'"
    )
    if cur.fetchone() is None:
        cur.execute("""
            CREATE TABLE enrollment_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL REFERENCES nodes(id),
                code VARCHAR(64) NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("Created table: enrollment_codes")
    else:
        print("Table enrollment_codes already exists")

    conn.commit()
    conn.close()
    print("Migration done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
