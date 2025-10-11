import datetime

from sqlmodel import select

from src.db.database import get_session
from src.db.models import User
from src.modules.birthdays_module.user_validation.check_flagged_users import check_if_user_is_a_member
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def flag_users_by_server(client):
    async with get_session() as session:
        query = select(User).where(User.is_member == True)
        servers_and_users = await session.exec(query)
        servers_and_users = servers_and_users.all()

        for each in servers_and_users:
            server_id = each.server_id
            user_id = each.user_id
            server = await client.fetch_guild(server_id)
            if not await check_if_user_is_a_member(server, user_id):
                await flag_user(user_id, server_id)
                user = await client.fetch_user(user_id)
                logger.info('flagged a user as not a member')
                logger.info(user.display_name)


async def flag_user(user_id, server_id):
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    async with get_session() as session:
        user = User(user_id=user_id, server_id=server_id, is_member=False, flagged_absent_at=utc_now)
        session.add(user)
        await session.commit()
        await session.refresh(user)
