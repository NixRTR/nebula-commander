"""
Database setup and session management for Nebula Commander
"""
import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)

# Ensure SQLite directory exists when using file-based URL (so data persists to disk)
_db_url = settings.database_url
if _db_url.startswith("sqlite"):
    # Extract path from sqlite+aiosqlite:///path (reject :memory: so we never use in-memory by accident)
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


async def init_db() -> None:
    """Create all tables. Import models so they register with Base.metadata."""
    from . import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
