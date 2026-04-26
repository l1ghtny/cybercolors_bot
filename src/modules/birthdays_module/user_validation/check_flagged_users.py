import discord
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import User
from src.modules.logs_setup import logger

logger = logger.logging.getLogger("bot")


async def remove_flag_from_users_by_server(client):
    async with get_async_session() as session:
        query = select(User).where(User.is_member == False)
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
                    logger.warning("Skipping unflag check: guild %s is not available", server_id)
                    continue
                except discord.HTTPException as error:
                    logger.warning("Skipping unflag check: failed to fetch guild %s (%s)", server_id, error)
                    continue

            if await check_if_user_is_a_member(server, user_id):
                await remove_flag_user(user_id, server_id)
                try:
                    user = await client.fetch_user(user_id)
                    username = user.display_name
                except discord.HTTPException:
                    username = str(user_id)
                logger.info('removed_flag_from_user')
                logger.info(username)


async def remove_flag_user(user_id, server_id):
    async with get_async_session() as session:
        user_to_update = await session.exec(select(User).where(User.user_id == user_id, User.server_id == server_id))
        user_updated = user_to_update.first()
        if user_updated is None:
            logger.warning("Cannot remove membership flag for missing row server=%s user=%s", server_id, user_id)
            return
        user_updated.is_member = True
        user_updated.flagged_absent_at = None
        session.add(user_updated)
        await session.commit()
        await session.refresh(user_updated)



async def check_if_user_is_a_member(server, user_id):
    member = server.get_member(user_id)
    if member is not None:
        return True

    try:
        await server.fetch_member(user_id)
        return True
    except discord.NotFound:
        return False
    except discord.Forbidden as error:
        logger.warning(
            "Failed to fetch member %s in guild %s because of missing permissions: %s",
            user_id,
            server.id,
            error,
        )
        return True
    except discord.HTTPException as error:
        logger.warning("Failed to fetch member %s in guild %s: %s", user_id, server.id, error)
        return True
