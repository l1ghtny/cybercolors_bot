from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.db_operations.dependencies import get_db_session

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get('/')
async def get_servers():
    return 'get_servers'


@servers.get('/{server_id}')
async def get_server(server_id, session: AsyncSession = Depends(get_db_session)):
    return 'get_server_by_id'


