import discord

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

    role = member.guild.get_role(settings.newcomer_role_id)
    if role is None:
        log.warning(
            "Newcomer role %s is configured but missing in guild %s.",
            settings.newcomer_role_id,
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

    if role in member.roles:
        return False

    await member.add_roles(
        role,
        reason="Automatic newcomer restriction",
    )
    return True
