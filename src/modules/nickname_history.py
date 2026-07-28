from __future__ import annotations

from collections.abc import Iterable

import discord
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import PastNickname
from src.modules.moderation.moderation_helpers import (
    check_if_server_exists,
    check_if_user_exists,
)


def _member_display_name(member: discord.Member | discord.User) -> str | None:
    value = (
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
    )
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


async def record_member_nickname_change(
    before: discord.Member,
    after: discord.Member,
) -> bool:
    """Persist the previous visible name after a server nickname change."""
    if after.bot or after.guild is None or before.nick == after.nick:
        return False

    previous_name = _member_display_name(before)
    if previous_name is None:
        return False

    return await _record_past_name(after, previous_name)


async def record_user_display_name_change(
    before: discord.User,
    after: discord.User,
    guilds: Iterable[discord.Guild],
) -> int:
    """Persist the previous global name where no server nickname overrides it."""
    before_name = _member_display_name(before)
    after_name = _member_display_name(after)
    if (
        after.bot
        or before_name is None
        or after_name is None
        or before_name == after_name
    ):
        return 0

    recorded = 0
    for guild in guilds:
        member = guild.get_member(after.id)
        if member is None or member.nick is not None:
            continue
        if await _record_past_name(member, before_name):
            recorded += 1
    return recorded


async def _record_past_name(member: discord.Member, nickname: str) -> bool:
    if member.guild is None:
        return False

    server_id = member.guild.id
    async with get_async_session() as session:
        await check_if_server_exists(member.guild, session)
        await check_if_user_exists(member, member.guild, session)

        latest = (
            await session.exec(
                select(PastNickname)
                .where(
                    PastNickname.user_id == member.id,
                    PastNickname.server_id == server_id,
                )
                .order_by(PastNickname.recorded_at.desc())
                .limit(1)
            )
        ).first()
        if latest is not None and latest.discord_name == nickname:
            await session.commit()
            return False

        session.add(
            PastNickname(
                user_id=member.id,
                discord_name=nickname,
                server_name=member.guild.name,
                server_id=server_id,
            )
        )
        await session.commit()
    return True
