import discord
from datetime import timedelta

from api.services.moderation_core import get_or_create_server_record, get_or_create_user_membership, naive_utcnow
from api.services.monitoring_service import upsert_monitored_user
from src.db.database import get_async_session
from src.db.models import ServerSecuritySettings
from src.modules.logs_setup import logger

log = logger.logging.getLogger("bot")


async def handle_new_member_restriction(member: discord.Member) -> bool:
    if member.bot or member.guild is None:
        return False

    async with get_async_session() as session:
        settings = await session.get(ServerSecuritySettings, member.guild.id)

    if (
        settings is None
        or not settings.newcomer_restriction_enabled
        or settings.newcomer_role_id is None
    ):
        return False

    newcomer_role_id = settings.newcomer_role_id
    auto_release_minutes = settings.newcomer_auto_release_minutes

    role = member.guild.get_role(newcomer_role_id)
    if role is None:
        log.warning(
            "Newcomer role %s is configured but missing in guild %s.",
            newcomer_role_id,
            member.guild.id,
        )
        return False

    bot_member = member.guild.me
    if bot_member is not None and role >= bot_member.top_role:
        log.warning(
            "Newcomer role %s is not assignable by bot in guild %s due to role hierarchy.",
            role.id,
            member.guild.id,
        )
        return False

    release_due_at = (
        naive_utcnow() + timedelta(minutes=auto_release_minutes)
        if auto_release_minutes
        else None
    )
    async with get_async_session() as session:
        await get_or_create_server_record(member.guild.id, session)
        await get_or_create_user_membership(
            session=session,
            server_id=member.guild.id,
            user_id=member.id,
            username=str(member),
            server_nickname=member.display_name,
        )
        await upsert_monitored_user(
            session=session,
            server_id=member.guild.id,
            user_id=member.id,
            reason="Automatic newcomer restriction",
            added_by_user_id=member.id,
            source="newcomer",
            release_due_at=release_due_at,
        )
        await session.commit()
    if role in member.roles:
        return False
    await member.add_roles(
        role,
        reason="Automatic newcomer restriction",
    )
    return True
