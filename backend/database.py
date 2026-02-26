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
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class EncryptedText(TypeDecorator):
    """Stores encrypted string in DB (base64 of magic+Fernet token). Transparent encrypt on bind, decrypt on result."""

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
        from .services.encryption import decrypt_to_str
        return decrypt_to_str(value)


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
        ]:
            if col not in node_columns:
                cur.execute(sql)
                logger.info("Migration: added column nodes.%s", col)
        cur.execute("PRAGMA table_info(networks)")
        net_columns = {row[1] for row in cur.fetchall()}
        for col, sql in [
            ("firewall_outbound_action", "ALTER TABLE networks ADD COLUMN firewall_outbound_action VARCHAR(32)"),
            ("firewall_inbound_action", "ALTER TABLE networks ADD COLUMN firewall_inbound_action VARCHAR(32)"),
            ("firewall_outbound_rules", "ALTER TABLE networks ADD COLUMN firewall_outbound_rules TEXT"),
            ("firewall_inbound_rules", "ALTER TABLE networks ADD COLUMN firewall_inbound_rules TEXT"),
        ]:
            if col not in net_columns:
                cur.execute(sql)
                logger.info("Migration: added column networks.%s", col)
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
        
        # Create node_requests table
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='node_requests'"
        )
        if cur.fetchone() is None:
            cur.execute("""
                CREATE TABLE node_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network_id INTEGER NOT NULL REFERENCES networks(id),
                    requested_by_user_id INTEGER NOT NULL REFERENCES users(id),
                    hostname VARCHAR(255) NOT NULL,
                    groups TEXT,
                    is_lighthouse BOOLEAN DEFAULT 0,
                    is_relay BOOLEAN DEFAULT 0,
                    status VARCHAR(32) DEFAULT 'pending',
                    approved_by_user_id INTEGER REFERENCES users(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processed_at DATETIME,
                    rejection_reason TEXT,
                    created_node_id INTEGER REFERENCES nodes(id)
                )
            """)
            logger.info("Migration: created table node_requests")
        
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
