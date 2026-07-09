import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, AsyncIterator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.config import get_database_url

load_dotenv()

# It's a good practice to load environment variables once
DATABASE_URL = get_database_url()

# Engine tuning for long-lived API processes:
# - pool_pre_ping avoids stale idle connections causing first-request 500s
# - pool_recycle proactively refreshes connections before server-side idle timeouts
DB_ECHO = os.getenv("DB_ECHO", "true").lower() == "true"
DB_POOL_RECYCLE_SECONDS = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))

# The engine is the source of database connectivity.
# echo=True is great for debugging as it logs all SQL statements.
engine = create_async_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    pool_pre_ping=True,
    pool_recycle=DB_POOL_RECYCLE_SECONDS,
)


def get_pool_status() -> dict[str, object]:
    pool = engine.sync_engine.pool
    status: dict[str, object] = {"class": pool.__class__.__name__, "status": pool.status()}
    for attr in ("size", "checkedout", "checkedin", "overflow"):
        value = getattr(pool, attr, None)
        if callable(value):
            try:
                status[attr] = value()
            except Exception:
                continue
    return status


def log_pool_status(logger: logging.Logger, context: str) -> None:
    try:
        logger.info("Database pool status %s: %s", context, get_pool_status())
    except Exception as error:
        logger.debug("Failed to collect database pool status for %s: %s", context, error)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session,
    handles commits, rollbacks, and closing.
    """
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            # The 'async with' context manager ensures the session is closed.
            # This 'finally' block is for clarity and to ensure cleanup even if something unexpected happens.
            await session.close()


@asynccontextmanager
async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
