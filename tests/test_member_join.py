import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import discord
from sqlmodel import select

from src.db.database import engine, get_async_session
from src.db.models import GlobalUser, Server, User
from src.modules.moderation.moderation_helpers import check_if_user_exists


def _make_discord_id() -> int:
    return 7_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def _member(*, user_id: int, nickname: str, joined_at: datetime) -> discord.Member:
    member = Mock(spec=discord.Member)
    member.id = user_id
    member.name = f"user-{user_id}"
    member.nick = nickname
    member.created_at = joined_at - timedelta(days=30)
    member.joined_at = joined_at
    member.display_avatar = None
    return member


async def _join_and_rejoin_scenario() -> None:
    await engine.dispose()
    server_id = _make_discord_id()
    user_id = _make_discord_id()
    first_joined_at = datetime(2026, 7, 1, 12, 0, 0)
    second_joined_at = datetime(2026, 7, 16, 9, 30, 0)

    guild = Mock(spec=discord.Guild)
    guild.id = server_id
    guild.name = f"server-{server_id}"

    member = _member(user_id=user_id, nickname="first nickname", joined_at=first_joined_at)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name=guild.name, bot_active=True))
        await session.flush()
        await check_if_user_exists(member, guild, session)
        await session.commit()

    async with get_async_session() as session:
        global_user = await session.get(GlobalUser, user_id)
        membership = (
            await session.exec(
                select(User).where(
                    User.user_id == user_id,
                    User.server_id == server_id,
                )
            )
        ).first()
        assert global_user is not None
        assert membership is not None
        assert membership.server_nickname == "first nickname"
        assert membership.joined_server_at == first_joined_at
        assert membership.is_member is True

        membership.is_member = False
        membership.left_server_at = datetime(2026, 7, 10, 18, 0, 0)
        session.add(membership)
        await session.commit()

    member.nick = "returning nickname"
    member.joined_at = second_joined_at

    async with get_async_session() as session:
        await check_if_user_exists(member, guild, session)
        await session.commit()

    async with get_async_session() as session:
        membership = (
            await session.exec(
                select(User).where(
                    User.user_id == user_id,
                    User.server_id == server_id,
                )
            )
        ).one()
        assert membership.server_nickname == "returning nickname"
        assert membership.joined_server_at == second_joined_at
        assert membership.left_server_at is None
        assert membership.is_member is True

    await engine.dispose()


def test_check_if_user_exists_creates_membership_and_handles_rejoin() -> None:
    asyncio.run(_join_and_rejoin_scenario())
