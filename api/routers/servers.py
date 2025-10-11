from fastapi import APIRouter

servers = APIRouter(prefix="/servers", tags=["servers"])


@servers.get('/')
async def get_servers():
    return 'get_servers'


@servers.get('/{server_id}')
async def get_server(server_id):
    return 'get_server_by_id'


