from fastapi import APIRouter

replies = APIRouter(prefix="/replies", tags=["replies"])


@replies.get('/{server_id}')
async def get_replies_by_server_id(server_id: int):
    return f'get_replies_by_{server_id}'
