from datetime import timedelta

import discord
from sqlmodel import select

from api.services.moderation_core import (
    get_or_create_server_record,
    get_or_create_user_membership,
    naive_utcnow,
)
from api.services.monitoring_service import upsert_monitored_user
from src.db.database import get_async_session
from src.db.models import MonitoredUser, ServerSecuritySettings
from src.modules.logs_setup import logger

log = logger.logging.getLogger("bot")


async def handle_newcomer_role_granted(
    before: discord.Member,
    after: discord.Member,
) -> bool:
    if after.bot or after.guild is None:
        return False

    async with get_async_session() as session:
        settings = await session.get(ServerSecuritySettings, after.guild.id)
        if (
            settings is None
            or not settings.newcomer_restriction_enabled
            or settings.newcomer_role_id is None
            or settings.newcomer_member_role_id is None
        ):
            return False

        newcomer_role_id = settings.newcomer_role_id
        member_role_id = settings.newcomer_member_role_id
        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}
        if newcomer_role_id not in after_role_ids or newcomer_role_id in before_role_ids:
            return False
        if member_role_id in after_role_ids:
            log.warning(
                "Skipping newcomer probation for user %s in guild %s because the member role is already assigned.",
                after.id,
                after.guild.id,
            )
            return False

        existing = (
            await session.exec(
                select(MonitoredUser).where(
                    MonitoredUser.server_id == after.guild.id,
                    MonitoredUser.user_id == after.id,
                    MonitoredUser.source == "newcomer",
                )
            )
        ).first()
        if existing is not None:
            return False

        release_due_at = (
            naive_utcnow() + timedelta(minutes=settings.newcomer_auto_release_minutes)
            if settings.newcomer_auto_release_minutes
            else None
        )
        await get_or_create_server_record(after.guild.id, session)
        await get_or_create_user_membership(
            session=session,
            server_id=after.guild.id,
            user_id=after.id,
            username=str(after),
            server_nickname=after.display_name,
        )
        await upsert_monitored_user(
            session=session,
            server_id=after.guild.id,
            user_id=after.id,
            reason="Automatic newcomer probation after rules acknowledgement",
            added_by_user_id=after.id,
            source="newcomer",
            release_due_at=release_due_at,
        )
        await session.commit()
    return True
