"""
One-time migration: encrypt existing plaintext data in DB and cert store.
Run before starting the app with encryption at rest for the first time.

Usage:
  Set NEBULA_COMMANDER_ENCRYPTION_KEY or NEBULA_COMMANDER_ENCRYPTION_KEY_FILE
  (same key you will use at runtime), then from repo root:

  python -m backend.scripts.migrate_encrypt

  Or: python backend/scripts/migrate_encrypt.py
"""
import base64
import sqlite3
import sys
from pathlib import Path

# Load config (and encryption key) before importing encryption helpers
def _load_config():
    from backend.config import settings  # noqa: F401
    return settings

def _db_path(settings):
    url = settings.database_url
    if not url.startswith("sqlite"):
        print("Migration only supports SQLite.", file=sys.stderr)
        sys.exit(1)
    path_part = url.split("///", 1)[-1].split("?")[0]
    if not path_part or path_part.startswith(":"):
        print("Could not get database path from database_url.", file=sys.stderr)
        sys.exit(1)
    return Path(path_part)


def _is_encrypted(value: str) -> bool:
    """Return True if value looks like our encrypted format (base64 of MAGIC+token)."""
    if not value or len(value) < 20:
        return False
    try:
        raw = base64.b64decode(value, validate=True)
        from backend.services.encryption import MAGIC
        return raw.startswith(MAGIC)
    except Exception:
        return False


def migrate_db(settings):
    from backend.services.encryption import encrypt_to_str

    db_path = _db_path(settings)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # nodes.public_key
    cur.execute("SELECT id, public_key FROM nodes WHERE public_key IS NOT NULL")
    n = 0
    for row in cur.fetchall():
        val = row["public_key"]
        if not _is_encrypted(val):
            cur.execute("UPDATE nodes SET public_key = ? WHERE id = ?", (encrypt_to_str(val), row["id"]))
            n += 1
    if n:
        print(f"Encrypted {n} node(s) public_key")

    # enrollment_codes.code
    cur.execute("SELECT id, code FROM enrollment_codes")
    n = 0
    for row in cur.fetchall():
        val = row["code"]
        if not _is_encrypted(val):
            cur.execute("UPDATE enrollment_codes SET code = ? WHERE id = ?", (encrypt_to_str(val), row["id"]))
            n += 1
    if n:
        print(f"Encrypted {n} enrollment_code(s)")

    # invitations.token
    cur.execute("SELECT id, token FROM invitations")
    n = 0
    for row in cur.fetchall():
        val = row["token"]
        if not _is_encrypted(val):
            cur.execute("UPDATE invitations SET token = ? WHERE id = ?", (encrypt_to_str(val), row["id"]))
            n += 1
    if n:
        print(f"Encrypted {n} invitation(s) token")

    # network_configs.config_yaml
    cur.execute("SELECT id, config_yaml FROM network_configs")
    n = 0
    for row in cur.fetchall():
        val = row["config_yaml"]
        if not _is_encrypted(val):
            cur.execute("UPDATE network_configs SET config_yaml = ? WHERE id = ?", (encrypt_to_str(val), row["id"]))
            n += 1
    if n:
        print(f"Encrypted {n} network_config(s) config_yaml")

    conn.commit()
    conn.close()
    print("DB migration done.")


def migrate_cert_store(settings):
    from backend.services.encryption import MAGIC
    from backend.services.cert_store import write_cert_store_file

    cert_store = Path(settings.cert_store_path)
    if not cert_store.exists():
        print(f"Cert store not found: {cert_store}", file=sys.stderr)
        return

    count = 0
    for path in cert_store.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if data.startswith(MAGIC):
            continue
        # Plaintext: re-write encrypted
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            print(f"Skipping non-UTF-8 file: {path}", file=sys.stderr)
            continue
        write_cert_store_file(path, content)
        count += 1
        print(f"Encrypted {path}")
    if count:
        print(f"Cert store: encrypted {count} file(s).")
    else:
        print("Cert store: no plaintext files to encrypt.")


def main():
    print("Loading config (encryption key required)...")
    try:
        settings = _load_config()
    except SystemExit as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print("Migrating database...")
    migrate_db(settings)
    print("Migrating cert store...")
    migrate_cert_store(settings)
    print("Migration complete. You can start the app with the same encryption key.")


if __name__ == "__main__":
    main()
