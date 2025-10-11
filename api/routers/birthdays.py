from fastapi import APIRouter

birthdays = APIRouter(prefix="/birthdays", tags=["birthdays"])


@birthdays.get('/{server_id}')
async def get_birthdays_by_server_id(server_id: int):
    return f'get_birthdays_by_{server_id}'
