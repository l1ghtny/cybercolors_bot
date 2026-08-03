import datetime

import discord
from sqlalchemy.orm import selectinload

from sqlmodel import select

from src.db.models import User, Birthday
from src.modules.logs_setup import logger
from src.db.database import get_async_session

logger = logger.logging.getLogger("bot")


def birthday_role_age(
    role_added_at: datetime.datetime,
    *,
    now: datetime.datetime | None = None,
) -> datetime.timedelta:
    """Return a birthday role's age using UTC-aware timestamps.

    PostgreSQL returns ``TIMESTAMP WITH TIME ZONE`` values as aware datetimes,
    while older databases and tests may still provide naive UTC values.
    """
    current_time = now or datetime.datetime.now(datetime.timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=datetime.timezone.utc)
    if role_added_at.tzinfo is None:
        role_added_at = role_added_at.replace(tzinfo=datetime.timezone.utc)

    return current_time.astimezone(datetime.timezone.utc) - role_added_at.astimezone(datetime.timezone.utc)


async def check_roles(client):
    async with get_async_session() as session:
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
            try:
                role_age = birthday_role_age(role_time)
            except (AttributeError, TypeError, ValueError):
                logger.exception(
                    'Invalid birthday role timestamp for user ID %s in server ID %s: %r',
                    role_user_id,
                    role_guild_id,
                    role_time,
                )
                continue
            current_guild = client.get_guild(role_guild_id)
            current_member = current_guild.get_member(role_user_id) if current_guild else None
            current_role = discord.utils.get(current_guild.roles, id=server_role_id) if current_guild and server_role_id else None
            logger.info(f'timedelta in days: {role_age.days}')
            if role_age >= datetime.timedelta(days=1) and current_member and current_role:
                logger.info('checked role is older than 1 day')
                try:
                    await current_member.remove_roles(current_role)
                except (discord.Forbidden, discord.HTTPException) as error:
                    logger.warning(
                        'Could not remove birthday role ID %s from user ID %s in server ID %s: %s',
                        server_role_id,
                        role_user_id,
                        role_guild_id,
                        error,
                    )
                    continue

                birthday.role_added_at = None
                await session.merge(birthday)
                await session.commit()
                logger.info(f'role removed from user {discord_user.name if discord_user else role_user_id}')
            else:
                if current_role and discord_user:
                    logger.info(f'role {current_role.name} on user {discord_user.name} is not older than 1 day')
                else:
                    logger.info('Skipping role check due to missing guild/member/role context')
