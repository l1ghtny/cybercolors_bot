from typing import AsyncGenerator
from sqlmodel.ext.asyncio.session import AsyncSession
from src.db.database import AsyncSessionLocal

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session and ensures it's closed.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()