from sqlmodel import select

from src.db.database import get_session
from src.db.models import User
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def remove_flag_from_users_by_server(client):
    async with get_session() as session:
        query = select(User).where(User.is_member == True)
        servers_and_users = await session.exec(query)
        servers_and_users = servers_and_users.all()
        for each in servers_and_users:
            server_id = each.server_id
            user_id = each.user_id
            server = await client.fetch_guild(server_id)
            if not await check_if_user_is_a_member(server, user_id):
                await remove_flag_user(user_id, server_id)
                user = await client.fetch_user(user_id)
                logger.info('removed_flag_from_user')
                logger.info(user.display_name)


async def remove_flag_user(user_id, server_id):
    async with get_session() as session:
        user_to_update = await session.exec(select(User).where(User.user_id == user_id, User.server_id == server_id))
        user_updated = user_to_update.first()
        user_updated.is_member = True
        session.add(user_updated)
        await session.commit()
        await session.refresh(user_updated)



async def check_if_user_is_a_member(server, user_id):
    if await server.fetch_member(user_id) is None:
        is_member = False
    else:
        is_member = True
    return is_member
