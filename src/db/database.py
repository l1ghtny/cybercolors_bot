import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker

load_dotenv()

# It's a good practice to load environment variables once
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# The engine is the source of database connectivity.
# echo=True is great for debugging as it logs all SQL statements.
engine = create_async_engine(DATABASE_URL, echo=True)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session,
    handles commits, rollbacks, and closing.
    """
    async with AsyncSession(engine) as session:
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