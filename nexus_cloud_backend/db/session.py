"""
nexus_cloud_backend/db/session.py

Database session management for the NEXUS Cloud backend.

Provides async and sync session factories, plus a FastAPI dependency
for injecting DB sessions into route handlers.
"""

import logging
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.db.models import Base

logger = logging.getLogger("nexus.cloud.db")

# ── Engines ──────────────────────────────────────────────────────────────

_settings = get_settings()

# Async engine (for FastAPI routes)
async_engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=_settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Sync engine (for Alembic migrations, scripts)
sync_engine = create_engine(
    _settings.DATABASE_SYNC_URL,
    echo=_settings.DEBUG,
    pool_size=5,
    max_overflow=10,
)

# ── Session Factories ────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
)


# ── FastAPI Dependencies ─────────────────────────────────────────────────

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session for the request lifetime."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_db() -> Generator[Session, None, None]:
    """Sync DB session for scripts and background tasks."""
    with SyncSessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# ── Table Creation ───────────────────────────────────────────────────────

def create_all_tables():
    """Create all tables defined in models.py. Used for dev/test setup."""
    Base.metadata.create_all(bind=sync_engine)
    logger.info("All database tables created")


def drop_all_tables():
    """Drop all tables. Used for test teardown only."""
    Base.metadata.drop_all(bind=sync_engine)
    logger.warning("All database tables dropped")