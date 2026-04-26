from datetime import datetime, timezone

import discord
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import Server


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _guild_icon_url(guild: discord.Guild) -> str | None:
    icon = getattr(guild, "icon", None)
    return str(icon.url) if icon else None


async def mark_guild_presence(guild: discord.Guild, is_active: bool) -> None:
    now = _naive_utcnow()
    async with get_async_session() as session:
        server = await session.get(Server, guild.id)
        if not server:
            server = Server(
                server_id=guild.id,
                server_name=guild.name,
                icon=_guild_icon_url(guild),
                bot_active=is_active,
                bot_joined_at=now if is_active else None,
                bot_left_at=None if is_active else now,
                bot_presence_updated_at=now,
            )
        else:
            server.server_name = guild.name
            server.icon = _guild_icon_url(guild)
            server.bot_active = is_active
            server.bot_presence_updated_at = now
            if is_active:
                server.bot_left_at = None
                if server.bot_joined_at is None:
                    server.bot_joined_at = now
            else:
                server.bot_left_at = now

        session.add(server)
        await session.commit()


async def sync_active_guild_presence(guilds: list[discord.Guild]) -> None:
    now = _naive_utcnow()
    active_ids = {guild.id for guild in guilds}

    async with get_async_session() as session:
        rows = (await session.exec(select(Server).where(Server.server_id.in_(list(active_ids))))).all() if active_ids else []
        existing_by_id = {row.server_id: row for row in rows}

        for guild in guilds:
            server = existing_by_id.get(guild.id)
            if not server:
                server = Server(
                    server_id=guild.id,
                    server_name=guild.name,
                    icon=_guild_icon_url(guild),
                    bot_active=True,
                    bot_joined_at=now,
                    bot_presence_updated_at=now,
                )
            else:
                server.server_name = guild.name
                server.icon = _guild_icon_url(guild)
                server.bot_active = True
                server.bot_left_at = None
                server.bot_presence_updated_at = now
                if server.bot_joined_at is None:
                    server.bot_joined_at = now
            session.add(server)

        currently_active_rows = (await session.exec(select(Server).where(Server.bot_active == True))).all()
        for server in currently_active_rows:
            if server.server_id in active_ids:
                continue
            server.bot_active = False
            server.bot_left_at = now
            server.bot_presence_updated_at = now
            session.add(server)

        await session.commit()
