from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_session
from src.db.models import Server

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get('/')
async def get_servers():
    return 'get_servers'


@servers.get('/{server_id}')
async def get_server(server_id: int, session: AsyncSession = Depends(get_session)):
    """Fetches a single server by its ID and returns it with stringified IDs."""
    server = await session.get(Server, server_id)
    if not server:
        return None  # Or raise HTTPException(404)

    server_data = server.model_dump()

    # **Explicitly convert all large integer IDs to strings**
    server_data['server_id'] = str(server.server_id)
    if server.birthday_channel_id:
        server_data['birthday_channel_id'] = str(server.birthday_channel_id)
    if server.birthday_role_id:
        server_data['birthday_role_id'] = str(server.birthday_role_id)

    return server_data


