import discord
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import User, utcnow_utc_tz
from src.modules.birthdays_module.user_validation.check_flagged_users import check_if_user_is_a_member
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def flag_users_by_server(client):
    async with get_async_session() as session:
        query = select(User).where(User.is_member == True)
        servers_and_users = await session.exec(query)
        servers_and_users = servers_and_users.all()

        for each in servers_and_users:
            server_id = each.server_id
            user_id = each.user_id
            server = client.get_guild(server_id)
            if server is None:
                try:
                    server = await client.fetch_guild(server_id)
                except discord.NotFound:
                    logger.warning("Skipping flag check: guild %s is not available", server_id)
                    continue
                except discord.HTTPException as error:
                    logger.warning("Skipping flag check: failed to fetch guild %s (%s)", server_id, error)
                    continue
            if not await check_if_user_is_a_member(server, user_id):
                await flag_user(user_id, server_id)
                try:
                    user = await client.fetch_user(user_id)
                    username = user.display_name
                except discord.HTTPException:
                    username = str(user_id)
                logger.info('flagged a user as not a member')
                logger.info(username)


async def flag_user(user_id, server_id):
    utc_now = utcnow_utc_tz()
    async with get_async_session() as session:
        query = select(User).where(User.user_id == user_id, User.server_id == server_id)
        result = await session.exec(query)
        user = result.first()

        if user is None:
            user = User(user_id=user_id, server_id=server_id, is_member=False, flagged_absent_at=utc_now)
        else:
            user.is_member = False
            user.flagged_absent_at = utc_now

        session.add(user)
        await session.commit()
        await session.refresh(user)
