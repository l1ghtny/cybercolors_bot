from datetime import datetime, timezone

import discord
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import ActionType, ModerationAction, Server, ServerModerationSettings


def naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_moderation_settings(
    session: AsyncSession,
    server_id: int,
    server_name: str,
) -> ServerModerationSettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=server_name)
        session.add(server)
        await session.flush()

    settings = await session.get(ServerModerationSettings, server_id)
    if settings:
        return settings

    settings = ServerModerationSettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def get_active_mute_actions_for_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> list[ModerationAction]:
    statement = (
        select(ModerationAction)
        .where(
            ModerationAction.server_id == server_id,
            ModerationAction.target_user_id == user_id,
            ModerationAction.action_type == ActionType.MUTE,
            ModerationAction.is_active == True,
        )
        .order_by(ModerationAction.created_at.desc())
    )
    return (await session.exec(statement)).all()


async def deactivate_user_mutes(
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> int:
    actions = await get_active_mute_actions_for_user(session=session, server_id=server_id, user_id=user_id)
    now = naive_utcnow()
    for action in actions:
        action.is_active = False
        action.expires_at = action.expires_at or now
        session.add(action)
    await session.flush()
    return len(actions)


async def get_expired_active_mutes(
    session: AsyncSession,
    limit: int = 200,
) -> list[ModerationAction]:
    now = naive_utcnow()
    statement = (
        select(ModerationAction)
        .where(
            ModerationAction.action_type == ActionType.MUTE,
            ModerationAction.is_active == True,
            ModerationAction.expires_at.is_not(None),
            ModerationAction.expires_at <= now,
        )
        .order_by(ModerationAction.expires_at.asc())
        .limit(limit)
    )
    return (await session.exec(statement)).all()


async def try_reconnect_voice_member(member: discord.Member, reason: str):
    if member.voice is None or member.voice.channel is None:
        return

    original_channel = member.voice.channel
    await member.move_to(None, reason=reason)
    await member.move_to(original_channel, reason=reason)
