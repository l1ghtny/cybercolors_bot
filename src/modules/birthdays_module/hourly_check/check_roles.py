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


async def check_roles(client, *, guild_ids: set[int] | None = None):
    if guild_ids is not None and not guild_ids:
        return
    async with get_async_session() as session:
        query = (
            select(User, Birthday)
            .join(Birthday, Birthday.user_id == User.user_id)
            .where(Birthday.role_added_at.isnot(None))
            .options(selectinload(User.server))
        )
        if guild_ids is not None:
            query = query.where(User.server_id.in_(list(guild_ids)))
        result = await session.exec(query)
        items = result.all()

        # The assignment timestamp is global per Discord user, while birthday
        # roles are server-specific. Process every membership before clearing
        # the shared timestamp so a commit cannot invalidate later rows.
        memberships_by_user: dict[int, tuple[Birthday, list[User]]] = {}
        for user, birthday in items:
            _, memberships = memberships_by_user.setdefault(
                user.user_id,
                (birthday, []),
            )
            memberships.append(user)

        timestamps_cleared = False
        for role_user_id, (birthday, memberships) in memberships_by_user.items():
            role_time = birthday.role_added_at
            try:
                role_age = birthday_role_age(role_time)
            except (AttributeError, TypeError, ValueError):
                logger.exception(
                    'Invalid birthday role timestamp for user ID %s across server IDs %s: %r',
                    role_user_id,
                    [membership.server_id for membership in memberships],
                    role_time,
                )
                continue
            logger.info(f'timedelta in days: {role_age.days}')
            if role_age < datetime.timedelta(days=1):
                continue

            logger.info('checked role is older than 1 day')
            all_roles_managed = True
            for membership in memberships:
                role_guild_id = membership.server_id
                server_role_id = membership.server.birthday_role_id if membership.server else None
                current_guild = client.get_guild(role_guild_id)
                if current_guild is None:
                    all_roles_managed = False
                    logger.warning(
                        'Could not manage birthday role for user ID %s because server ID %s is unavailable',
                        role_user_id,
                        role_guild_id,
                    )
                    continue

                current_member = current_guild.get_member(role_user_id)
                current_role = (
                    discord.utils.get(current_guild.roles, id=server_role_id)
                    if server_role_id
                    else None
                )
                if current_member is None or current_role is None:
                    logger.info(
                        'No birthday role to remove for user ID %s in server ID %s',
                        role_user_id,
                        role_guild_id,
                    )
                    continue

                try:
                    await current_member.remove_roles(current_role)
                except (discord.Forbidden, discord.HTTPException) as error:
                    all_roles_managed = False
                    logger.warning(
                        'Could not remove birthday role ID %s from user ID %s in server ID %s: %s',
                        server_role_id,
                        role_user_id,
                        role_guild_id,
                        error,
                    )
                    continue

                logger.info(
                    'Birthday role %s removed from user ID %s in server ID %s',
                    current_role.name,
                    role_user_id,
                    role_guild_id,
                )

            if all_roles_managed:
                birthday.role_added_at = None
                await session.merge(birthday)
                timestamps_cleared = True

        if timestamps_cleared:
            await session.commit()
