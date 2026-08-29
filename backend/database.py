"""
Database setup and session management for Nebula Commander
"""
import logging
import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator, Text

from .config import settings

logger = logging.getLogger(__name__)

# Ensure SQLite directory exists when using file-based URL (so data persists to disk)
_db_url = settings.database_url
if _db_url.startswith("sqlite"):
    # Extract path: ///path (relative) or ////absolute/path. Reject :memory: so we never use in-memory by accident.
    path_part = _db_url.split("///", 1)[-1].split("?")[0]
    if path_part and not path_part.startswith(":"):
        Path(path_part).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    _db_url,
    echo=settings.debug,
    future=True,
)

# SQLite: ensure commits are durable and use WAL for better concurrent read behavior
if _db_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class EncryptedText(TypeDecorator):
    """
    Stores encrypted string in DB (base64 of magic+Fernet token).
    Transparent encrypt on bind, decrypt on result.
    All writes to columns using this type must go through the ORM so process_bind_parameter
    runs; raw SQL that inserts/updates these columns must use encrypt_to_str() from
    backend.services.encryption (e.g. migrate_encrypt.py).
    """

    impl = Text
    cache_ok = True

    def process_bind_parameter(self, value, dialect):
        if value is None:
            return None
        from .services.encryption import encrypt_to_str
        return encrypt_to_str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        from .services.encryption import decrypt_to_str_or_plain
        return decrypt_to_str_or_plain(value)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


def _run_sqlite_migrations() -> None:
    """Add missing columns and tables to existing SQLite DB (safe to run every startup)."""
    if not _db_url.startswith("sqlite"):
        return
    path_part = _db_url.split("///", 1)[-1].split("?")[0]
    if not path_part or path_part.startswith(":"):
        return
    path = Path(path_part)
    if not path.exists():
        return
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(nodes)")
        node_columns = {row[1] for row in cur.fetchall()}
        for col, sql in [
            ("public_endpoint", "ALTER TABLE nodes ADD COLUMN public_endpoint VARCHAR(512)"),
            ("lighthouse_options", "ALTER TABLE nodes ADD COLUMN lighthouse_options TEXT"),
            ("logging_options", "ALTER TABLE nodes ADD COLUMN logging_options TEXT"),
            ("is_relay", "ALTER TABLE nodes ADD COLUMN is_relay BOOLEAN DEFAULT 0"),
            ("first_polled_at", "ALTER TABLE nodes ADD COLUMN first_polled_at DATETIME"),
            ("punchy_options", "ALTER TABLE nodes ADD COLUMN punchy_options TEXT"),
            ("platform", "ALTER TABLE nodes ADD COLUMN platform VARCHAR(16) DEFAULT 'desktop'"),
        ]:
            if col not in node_columns:
                cur.execute(sql)
                logger.info("Migration: added column nodes.%s", col)
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='network_group_firewall'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE network_group_firewall (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network_id INTEGER NOT NULL REFERENCES networks(id),
                    group_name VARCHAR(255) NOT NULL,
                    outbound_rules TEXT,
                    inbound_rules TEXT,
                    UNIQUE (network_id, group_name)
                )
            """)
            logger.info("Migration: created table network_group_firewall")
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
            logger.info("Migration: created table enrollment_codes")
        
        # Add system_role column to users table
        cur.execute("PRAGMA table_info(users)")
        user_columns = {row[1] for row in cur.fetchall()}
        if "system_role" not in user_columns:
            cur.execute("ALTER TABLE users ADD COLUMN system_role VARCHAR(64) DEFAULT 'user'")
            logger.info("Migration: added column users.system_role")
            # Migrate existing users: set system_role based on legacy role
            cur.execute("UPDATE users SET system_role = 'system-admin' WHERE role = 'admin'")
            logger.info("Migration: migrated existing admin users to system-admin role")
        
        # Create network_permissions table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='network_permissions'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE network_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    network_id INTEGER NOT NULL REFERENCES networks(id),
                    role VARCHAR(32) NOT NULL,
                    can_manage_nodes BOOLEAN DEFAULT 0,
                    can_invite_users BOOLEAN DEFAULT 0,
                    can_manage_firewall BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    invited_by_user_id INTEGER REFERENCES users(id),
                    UNIQUE (user_id, network_id)
                )
            """)
            logger.info("Migration: created table network_permissions")
        
        # Create node_permissions table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='node_permissions'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE node_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    node_id INTEGER NOT NULL REFERENCES nodes(id),
                    can_view_details BOOLEAN DEFAULT 1,
                    can_download_config BOOLEAN DEFAULT 1,
                    can_download_cert BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    granted_by_user_id INTEGER REFERENCES users(id),
                    UNIQUE (user_id, node_id)
                )
            """)
            logger.info("Migration: created table node_permissions")
        
        # node_requests: removed (workflow was never functional - see backend/api/node_requests.py
        # deletion). Drop the table on any DB that has it from an earlier version.
        cur.execute("DROP TABLE IF EXISTS node_requests")

        # network_configs: removed (config was always generated on the fly; this table was
        # never inserted into, only ever deleted from on node deletion). Drop on upgrade.
        cur.execute("DROP TABLE IF EXISTS network_configs")

        # Create access_grants table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='access_grants'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE access_grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_user_id INTEGER NOT NULL REFERENCES users(id),
                    resource_type VARCHAR(32) NOT NULL,
                    resource_id INTEGER NOT NULL,
                    granted_by_user_id INTEGER NOT NULL REFERENCES users(id),
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    revoked_at DATETIME,
                    reason TEXT
                )
            """)
            logger.info("Migration: created table access_grants")
        
        # Create network_settings table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='network_settings'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE network_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network_id INTEGER NOT NULL UNIQUE REFERENCES networks(id),
                    auto_approve_nodes BOOLEAN DEFAULT 0,
                    default_node_groups TEXT,
                    default_is_lighthouse BOOLEAN DEFAULT 0,
                    default_is_relay BOOLEAN DEFAULT 0
                )
            """)
            logger.info("Migration: created table network_settings")
        
        # Create invitations table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='invitations'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE invitations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL,
                    network_id INTEGER NOT NULL REFERENCES networks(id),
                    invited_by_user_id INTEGER NOT NULL REFERENCES users(id),
                    token VARCHAR(128) NOT NULL UNIQUE,
                    role VARCHAR(32) NOT NULL,
                    can_manage_nodes BOOLEAN DEFAULT 0,
                    can_invite_users BOOLEAN DEFAULT 0,
                    can_manage_firewall BOOLEAN DEFAULT 0,
                    status VARCHAR(32) DEFAULT 'pending',
                    expires_at DATETIME NOT NULL,
                    accepted_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    email_status VARCHAR(32) DEFAULT 'not_sent',
                    email_sent_at DATETIME,
                    email_error VARCHAR(512)
                )
            """)
            logger.info("Migration: created table invitations")
        
        # Add email status columns to existing invitations table
        cur.execute("PRAGMA table_info(invitations)")
        invitation_columns = {row[1] for row in cur.fetchall()}
        for col, sql in [
            ("email_status", "ALTER TABLE invitations ADD COLUMN email_status VARCHAR(32) DEFAULT 'not_sent'"),
            ("email_sent_at", "ALTER TABLE invitations ADD COLUMN email_sent_at DATETIME"),
            ("email_error", "ALTER TABLE invitations ADD COLUMN email_error VARCHAR(512)"),
        ]:
            if col not in invitation_columns:
                cur.execute(sql)
                logger.info("Migration: added column invitations.%s", col)
        
        # Create audit_log table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at DATETIME NOT NULL,
                    action VARCHAR(64) NOT NULL,
                    actor_user_id INTEGER REFERENCES users(id),
                    actor_identifier VARCHAR(255),
                    resource_type VARCHAR(32),
                    resource_id INTEGER,
                    result VARCHAR(16) NOT NULL DEFAULT 'success',
                    details TEXT,
                    client_ip VARCHAR(64)
                )
            """)
            cur.execute(
                "CREATE INDEX ix_audit_log_occurred_at ON audit_log (occurred_at DESC)"
            )
            logger.info("Migration: created table audit_log")

        # Add device_token_version column to nodes table
        cur.execute("PRAGMA table_info(nodes)")
        node_columns = {row[1] for row in cur.fetchall()}
        if "device_token_version" not in node_columns:
            cur.execute(
                "ALTER TABLE nodes ADD COLUMN device_token_version INTEGER DEFAULT 1"
            )
            logger.info("Migration: added column nodes.device_token_version")

        # Add upstream_servers to network_dns_configs
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='network_dns_configs'"
        )
        if cur.fetchone() is not None:
            cur.execute("PRAGMA table_info(network_dns_configs)")
            dns_cfg_columns = {row[1] for row in cur.fetchall()}
            if "upstream_servers" not in dns_cfg_columns:
                cur.execute(
                    "ALTER TABLE network_dns_configs ADD COLUMN upstream_servers TEXT"
                )
                logger.info("Migration: added column network_dns_configs.upstream_servers")
            if "extra_dns_resolvers" not in dns_cfg_columns:
                cur.execute(
                    "ALTER TABLE network_dns_configs ADD COLUMN extra_dns_resolvers TEXT"
                )
                logger.info("Migration: added column network_dns_configs.extra_dns_resolvers")

        # Create auth_exchange_codes table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_exchange_codes'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE auth_exchange_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(64) NOT NULL UNIQUE,
                    token TEXT NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("Migration: created table auth_exchange_codes")

        # Create reauth_challenges table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reauth_challenges'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE reauth_challenges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_sub VARCHAR(255) NOT NULL UNIQUE,
                    challenge VARCHAR(128) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    authenticated_at DATETIME
                )
            """)
            logger.info("Migration: created table reauth_challenges")

        # Add is_placeholder column to users table (marks the reserved "deleted
        # user" sentinel row - see backend/api/users.py::delete_user)
        cur.execute("PRAGMA table_info(users)")
        user_columns = {row[1] for row in cur.fetchall()}
        if "is_placeholder" not in user_columns:
            cur.execute("ALTER TABLE users ADD COLUMN is_placeholder BOOLEAN DEFAULT 0")
            logger.info("Migration: added column users.is_placeholder")

        # Ensure exactly one sentinel "deleted user" row exists, then repair any
        # rows already left dangling by a user delete under the old code (FK
        # enforcement has never been on, so this could already have happened).
        cur.execute("SELECT id FROM users WHERE is_placeholder = 1 LIMIT 1")
        sentinel_row = cur.fetchone()
        if sentinel_row is None:
            cur.execute(
                """
                INSERT INTO users (oidc_sub, email, system_role, is_placeholder, created_at)
                VALUES ('system:deleted-user', 'Deleted user', 'user', 1, CURRENT_TIMESTAMP)
                """
            )
            sentinel_id = cur.lastrowid
            logger.info("Migration: created sentinel placeholder user (id=%s)", sentinel_id)
        else:
            sentinel_id = sentinel_row[0]

        cur.execute(
            "UPDATE invitations SET invited_by_user_id = ? "
            "WHERE invited_by_user_id NOT IN (SELECT id FROM users)",
            (sentinel_id,),
        )
        if cur.rowcount:
            logger.info("Migration: repaired %d orphaned invitations.invited_by_user_id row(s)", cur.rowcount)
        cur.execute(
            "UPDATE access_grants SET granted_by_user_id = ? "
            "WHERE granted_by_user_id NOT IN (SELECT id FROM users)",
            (sentinel_id,),
        )
        if cur.rowcount:
            logger.info("Migration: repaired %d orphaned access_grants.granted_by_user_id row(s)", cur.rowcount)
        cur.execute(
            "UPDATE network_permissions SET invited_by_user_id = NULL "
            "WHERE invited_by_user_id IS NOT NULL AND invited_by_user_id NOT IN (SELECT id FROM users)"
        )
        if cur.rowcount:
            logger.info("Migration: repaired %d orphaned network_permissions.invited_by_user_id row(s)", cur.rowcount)
        cur.execute(
            "UPDATE node_permissions SET granted_by_user_id = NULL "
            "WHERE granted_by_user_id IS NOT NULL AND granted_by_user_id NOT IN (SELECT id FROM users)"
        )
        if cur.rowcount:
            logger.info("Migration: repaired %d orphaned node_permissions.granted_by_user_id row(s)", cur.rowcount)
        cur.execute(
            "UPDATE audit_log SET actor_user_id = NULL "
            "WHERE actor_user_id IS NOT NULL AND actor_user_id NOT IN (SELECT id FROM users)"
        )
        if cur.rowcount:
            logger.info("Migration: repaired %d orphaned audit_log.actor_user_id row(s)", cur.rowcount)

        conn.commit()
    finally:
        conn.close()


async def init_db() -> None:
    """Create all tables and run any pending migrations."""
    from . import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _run_sqlite_migrations()
    logger.info("Database initialized")


async def get_session():
    """FastAPI dependency: yield an async session. Commits on success so data persists."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
