from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_session
replies = APIRouter(prefix="/replies", tags=["replies"])


@replies.get('/{server_id}')
async def get_replies_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):
    return f'get_replies_by_{server_id}'
