from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_session

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get('/')
async def get_servers():
    return 'get_servers'


@servers.get('/{server_id}')
async def get_server(server_id, session: AsyncSession = Depends(get_session)):
    return 'get_server_by_id'


