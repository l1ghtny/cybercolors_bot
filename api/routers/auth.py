from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_session

auth = APIRouter(prefix="/auth", tags=["authentication"])


@auth.post('/login')
async def login(session: AsyncSession = Depends(get_session)):
    return 'login'


@auth.post('/logout')
async def logout(session: AsyncSession = Depends(get_session)):
    return 'logout'