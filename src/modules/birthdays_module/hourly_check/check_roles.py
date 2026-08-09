import datetime

import discord
from sqlalchemy.orm import selectinload

from sqlmodel import select

from src.db.models import Birthday, Server, User
from src.modules.logs_setup import logger
from src.db.database import get_async_session
from src.modules.observability.bot_metrics import (
    BIRTHDAY_ROLE_CLEANUP_PENDING,
    BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS,
    BIRTHDAY_ROLE_REMOVALS,
)

logger = logger.logging.getLogger("bot")


def birthday_is_today(
    birthday: Birthday,
    *,
    now: datetime.datetime | None = None,
) -> bool:
    """Return whether the birthday is active in the member's configured timezone."""
    if not birthday.timezone:
        return False
    try:
        from zoneinfo import ZoneInfo

        timezone = ZoneInfo(birthday.timezone)
    except (KeyError, ValueError):
        logger.warning(
            "Treating birthday role as stale because user ID %s has invalid timezone %r",
            birthday.user_id,
            birthday.timezone,
        )
        return False

    current_time = now or datetime.datetime.now(datetime.timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=datetime.timezone.utc)
    local_date = current_time.astimezone(timezone).date()
    return (local_date.month, local_date.day) == (birthday.month, birthday.day)


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


async def check_roles(
    client,
    *,
    guild_ids: set[int] | None = None,
    update_pending_metric: bool = True,
):
    if guild_ids is not None and not guild_ids:
        if update_pending_metric:
            BIRTHDAY_ROLE_CLEANUP_PENDING.set(0)
        return
    async with get_async_session() as session:
        query = (
            select(User)
            .where(User.birthday_role_added_at.isnot(None))
            .options(selectinload(User.server))
        )
        if guild_ids is not None:
            query = query.where(User.server_id.in_(list(guild_ids)))
        result = await session.exec(query)
        memberships = result.all()

        timestamps_cleared = 0
        pending_cleanups = 0
        for membership in memberships:
            role_time = membership.birthday_role_added_at
            role_user_id = membership.user_id
            role_guild_id = membership.server_id
            try:
                role_age = birthday_role_age(role_time)
            except (AttributeError, TypeError, ValueError):
                logger.exception(
                    'Invalid birthday role timestamp for user ID %s in server ID %s: %r',
                    role_user_id,
                    role_guild_id,
                    role_time,
                )
                BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(
                    outcome="invalid_timestamp"
                ).inc()
                pending_cleanups += 1
                continue
            logger.info(f'timedelta in days: {role_age.days}')
            if role_age < datetime.timedelta(days=1):
                continue

            logger.info('checked role is older than 1 day')
            server_role_id = membership.server.birthday_role_id if membership.server else None
            current_guild = client.get_guild(role_guild_id)
            if current_guild is None:
                BIRTHDAY_ROLE_REMOVALS.labels(outcome="server_unavailable").inc()
                BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(
                    outcome="retry_pending"
                ).inc()
                pending_cleanups += 1
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
                BIRTHDAY_ROLE_REMOVALS.labels(outcome="absent").inc()
                logger.info(
                    'No birthday role to remove for user ID %s in server ID %s',
                    role_user_id,
                    role_guild_id,
                )
            else:
                try:
                    await current_member.remove_roles(current_role)
                except (discord.Forbidden, discord.HTTPException) as error:
                    BIRTHDAY_ROLE_REMOVALS.labels(outcome="discord_error").inc()
                    BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(
                        outcome="retry_pending"
                    ).inc()
                    pending_cleanups += 1
                    logger.warning(
                        'Could not remove birthday role ID %s from user ID %s in server ID %s: %s',
                        server_role_id,
                        role_user_id,
                        role_guild_id,
                        error,
                    )
                    continue

                BIRTHDAY_ROLE_REMOVALS.labels(outcome="removed").inc()
                logger.info(
                    'Birthday role %s removed from user ID %s in server ID %s',
                    current_role.name,
                    role_user_id,
                    role_guild_id,
                )

            membership.birthday_role_added_at = None
            await session.merge(membership)
            timestamps_cleared += 1

        if timestamps_cleared:
            try:
                await session.commit()
            except Exception:
                BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(outcome="database_error").inc(
                    timestamps_cleared
                )
                pending_cleanups += timestamps_cleared
                if update_pending_metric:
                    BIRTHDAY_ROLE_CLEANUP_PENDING.set(pending_cleanups)
                raise
            BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(outcome="completed").inc(
                timestamps_cleared
            )
        if update_pending_metric:
            BIRTHDAY_ROLE_CLEANUP_PENDING.set(pending_cleanups)


async def reconcile_untracked_birthday_roles(
    client,
    *,
    guild_ids: set[int] | None = None,
) -> None:
    """Remove stale birthday roles that predate per-membership tracking.

    Older cleanup runs could clear the global timestamp after removing a role
    from only one guild. Those remaining Discord roles have no database marker,
    so the normal timestamp-based cleanup cannot discover them. Reconcile the
    configured role's actual holders while preserving roles for birthdays that
    are still active today and memberships that still have a pending timestamp.
    """
    if guild_ids is not None and not guild_ids:
        return

    async with get_async_session() as session:
        server_query = select(Server).where(Server.birthday_role_id.isnot(None))
        if guild_ids is not None:
            server_query = server_query.where(Server.server_id.in_(list(guild_ids)))
        server_result = await session.exec(server_query)

        for server in server_result.all():
            guild = client.get_guild(server.server_id)
            if guild is None:
                logger.warning(
                    "Could not reconcile untracked birthday roles because server ID %s is unavailable",
                    server.server_id,
                )
                continue

            role = discord.utils.get(guild.roles, id=server.birthday_role_id)
            if role is None:
                logger.warning(
                    "Could not reconcile untracked birthday roles because role ID %s is unavailable in server ID %s",
                    server.birthday_role_id,
                    server.server_id,
                )
                continue

            role_members = list(role.members)
            if not role_members:
                continue

            holder_ids = [member.id for member in role_members]
            birthday_result = await session.exec(
                select(Birthday).where(Birthday.user_id.in_(holder_ids))
            )
            birthdays = {birthday.user_id: birthday for birthday in birthday_result.all()}
            tracked_result = await session.exec(
                select(User.user_id).where(
                    User.server_id == server.server_id,
                    User.user_id.in_(holder_ids),
                    User.birthday_role_added_at.isnot(None),
                )
            )
            tracked_holder_ids = set(tracked_result.all())

            for member in role_members:
                if member.id in tracked_holder_ids:
                    continue
                birthday = birthdays.get(member.id)
                if birthday is not None and birthday_is_today(birthday):
                    continue

                try:
                    await member.remove_roles(
                        role,
                        reason="Removing stale birthday role left without cleanup state",
                    )
                except (discord.Forbidden, discord.HTTPException) as error:
                    BIRTHDAY_ROLE_REMOVALS.labels(outcome="discord_error").inc()
                    BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(
                        outcome="retry_pending"
                    ).inc()
                    logger.warning(
                        "Could not reconcile stale birthday role ID %s from user ID %s in server ID %s: %s",
                        role.id,
                        member.id,
                        server.server_id,
                        error,
                    )
                    continue

                BIRTHDAY_ROLE_REMOVALS.labels(outcome="removed").inc()
                BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS.labels(
                    outcome="reconciled"
                ).inc()
                logger.info(
                    "Reconciled stale birthday role %s from user ID %s in server ID %s",
                    role.name,
                    member.id,
                    server.server_id,
                )
