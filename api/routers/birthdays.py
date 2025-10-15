from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_session

birthdays = APIRouter(prefix="/birthdays", tags=["birthdays"])


@birthdays.get('/{server_id}')
async def get_birthdays_by_server_id(server_id: int, session: AsyncSession = Depends(get_session)):
    return f'get_birthdays_by_{server_id}'
