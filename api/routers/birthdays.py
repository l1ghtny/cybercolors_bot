from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.db_operations.dependencies import get_db_session

birthdays = APIRouter(prefix="/birthdays", tags=["birthdays"])


@birthdays.get('/{server_id}')
async def get_birthdays_by_server_id(server_id: int, session: AsyncSession = Depends(get_db_session)):
    return f'get_birthdays_by_{server_id}'
