import datetime

import discord
from sqlalchemy.orm import selectinload

from sqlmodel import select

from src.db.models import User, Birthday
from src.modules.logs_setup import logger
from src.db.database import get_session

logger = logger.logging.getLogger("bot")


async def check_roles(client):
    async with get_session() as session:
        query = (
            select(User, Birthday)
            .join(Birthday, Birthday.user_id == User.user_id)
            .where(Birthday.role_added_at.isnot(None))
            .options(selectinload(User.server))
        )
        result = await session.exec(query)
        items = result.all()

        for user, birthday in items:
            role_time = birthday.role_added_at
            role_guild_id = user.server_id
            role_user_id = user.user_id
            server_role_id = user.server.birthday_role_id if user.server else None

            discord_user = client.get_user(role_user_id)
            current_time_now = datetime.datetime.utcnow()
            timedelta = current_time_now - role_time
            current_guild = client.get_guild(role_guild_id)
            current_member = current_guild.get_member(role_user_id) if current_guild else None
            current_role = discord.utils.get(current_guild.roles, id=server_role_id) if current_guild and server_role_id else None
            logger.info(f'timedelta in days: {timedelta.days}')
            if timedelta.days >= 1 and current_member and current_role:
                logger.info('checked role is older than 1 day')
                await current_member.remove_roles(current_role)
                birthday.role_added_at = None
                await session.merge(birthday)
                await session.commit()
                logger.info(f'role removed from user {discord_user.name if discord_user else role_user_id}')
            else:
                if current_role and discord_user:
                    logger.info(f'role {current_role.name} on user {discord_user.name} is not older than 1 day')
                else:
                    logger.info('Skipping role check due to missing guild/member/role context')
