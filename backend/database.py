"""
Database setup and session management for Nebula Commander
"""
import logging
import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

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
        columns = {row[1] for row in cur.fetchall()}
        for col, sql in [
            ("public_endpoint", "ALTER TABLE nodes ADD COLUMN public_endpoint VARCHAR(512)"),
            ("lighthouse_options", "ALTER TABLE nodes ADD COLUMN lighthouse_options TEXT"),
            ("first_polled_at", "ALTER TABLE nodes ADD COLUMN first_polled_at DATETIME"),
        ]:
            if col not in columns:
                cur.execute(sql)
                logger.info("Migration: added column nodes.%s", col)
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
