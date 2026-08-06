import discord

from api.services.gateway_installations import (
    record_gateway_presence,
    sync_gateway_presence_snapshot,
)
from src.db.database import get_async_session


def _guild_icon_url(guild: discord.Guild) -> str | None:
    icon = getattr(guild, "icon", None)
    return str(icon.url) if icon else None


async def mark_guild_presence(
    guild: discord.Guild,
    is_active: bool,
    *,
    bot_profile: str = "cybercolors",
) -> str:
    async with get_async_session() as session:
        primary_profile = await record_gateway_presence(
            session,
            server_id=guild.id,
            server_name=guild.name,
            icon=_guild_icon_url(guild),
            profile_key=bot_profile,
            active=is_active,
        )
        await session.commit()
        return primary_profile


async def sync_active_guild_presence(
    guilds: list[discord.Guild],
    *,
    bot_profile: str = "cybercolors",
) -> None:
    async with get_async_session() as session:
        await sync_gateway_presence_snapshot(
            session,
            guilds=(
                (guild.id, guild.name, _guild_icon_url(guild))
                for guild in guilds
            ),
            profile_key=bot_profile,
        )
        await session.commit()
