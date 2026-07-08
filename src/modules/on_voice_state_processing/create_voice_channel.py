from __future__ import annotations

from datetime import datetime, timezone

import discord
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import (
    AIModerationDecision,
    ServerTempVoiceSettings,
    TempVoiceLog,
    TempVoiceParticipant,
    VoiceChannel,
)
from src.modules.logs_setup import logger
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

logger = logger.logging.getLogger("bot")

_recent_temp_voice_channels: set[tuple[int, int]] = set()


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_channel_name(template: str, member: discord.Member) -> str:
    display_name = (getattr(member, "display_name", None) or getattr(member, "name", None) or str(member.id)).strip()
    username = (getattr(member, "name", None) or display_name).strip()
    channel_name = template.format(display_name=display_name, username=username)
    channel_name = " ".join(channel_name.split())
    return (channel_name or f"{display_name}'s channel")[:100]


def temp_voice_owner_has_allowed_role(member: discord.Member, settings: ServerTempVoiceSettings) -> bool:
    allowed_role_ids = {str(role_id) for role_id in (settings.owner_control_allowed_role_ids or []) if str(role_id).strip()}
    if not allowed_role_ids:
        return True
    return any(str(role.id) in allowed_role_ids for role in getattr(member, "roles", []))


def temp_voice_owner_can_receive_native_manage(member: discord.Member, settings: ServerTempVoiceSettings) -> bool:
    return settings.owner_manage_channel_enabled and temp_voice_owner_has_allowed_role(member, settings)


async def _active_voice_channel(session, server_id: int, channel_id: int) -> VoiceChannel | None:
    return await session.get(VoiceChannel, (server_id, channel_id))


async def _active_temp_log(session, server_id: int, channel_id: int) -> TempVoiceLog | None:
    return (
        await session.exec(
            select(TempVoiceLog).where(
                TempVoiceLog.server_id == server_id,
                TempVoiceLog.channel_id == channel_id,
                TempVoiceLog.deleted_at.is_(None),
            )
        )
    ).first()


async def _create_temp_log(
    session,
    *,
    server_id: int,
    channel_id: int,
    channel_name: str,
    trigger_channel_id: int,
    owner_user_id: int,
) -> TempVoiceLog:
    temp_log = TempVoiceLog(
        server_id=server_id,
        channel_id=channel_id,
        trigger_channel_id=trigger_channel_id,
        owner_user_id=owner_user_id,
        channel_name=channel_name,
        created_at=_naive_utcnow(),
    )
    session.add(temp_log)
    await session.flush()
    return temp_log



async def _record_temp_voice_join(session, temp_log: TempVoiceLog, member: discord.Member, joined_at: datetime) -> None:
    existing = (
        await session.exec(
            select(TempVoiceParticipant).where(
                TempVoiceParticipant.log_id == temp_log.id,
                TempVoiceParticipant.user_id == member.id,
                TempVoiceParticipant.left_at.is_(None),
            )
        )
    ).first()
    if existing is not None:
        return
    session.add(
        TempVoiceParticipant(
            log_id=temp_log.id,
            server_id=temp_log.server_id,
            channel_id=temp_log.channel_id,
            user_id=member.id,
            joined_at=joined_at,
        )
    )


async def _close_temp_voice_participation(session, temp_log: TempVoiceLog, user_id: int, left_at: datetime) -> None:
    rows = (
        await session.exec(
            select(TempVoiceParticipant).where(
                TempVoiceParticipant.log_id == temp_log.id,
                TempVoiceParticipant.user_id == user_id,
                TempVoiceParticipant.left_at.is_(None),
            )
        )
    ).all()
    for row in rows:
        row.left_at = left_at
        session.add(row)


async def _record_temp_voice_participation(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    before_channel_id = before.channel.id if before.channel is not None else None
    after_channel_id = after.channel.id if after.channel is not None else None
    if before_channel_id == after_channel_id:
        return

    now = _naive_utcnow()
    async with get_async_session() as session:
        await check_if_server_exists(member.guild, session)
        await check_if_user_exists(member, member.guild, session)
        if before_channel_id is not None:
            before_log = await _active_temp_log(session, member.guild.id, before_channel_id)
            if before_log is not None:
                await _close_temp_voice_participation(session, before_log, member.id, now)
        if after_channel_id is not None:
            after_log = await _active_temp_log(session, member.guild.id, after_channel_id)
            if after_log is not None:
                await _record_temp_voice_join(session, after_log, member, now)
        await session.commit()

async def _grant_owner_permissions(channel: discord.VoiceChannel, member: discord.Member) -> None:
    overwrite = channel.overwrites_for(member)
    overwrite.manage_channels = True
    try:
        await channel.set_permissions(
            member,
            overwrite=overwrite,
            reason="Temporary voice owner can rename and tune their channel.",
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Could not grant temp voice owner permissions in channel %s: %s", channel.id, error)


async def _create_temp_channel(member: discord.Member, after: discord.VoiceState, settings: ServerTempVoiceSettings) -> None:
    if after.channel is None or settings.trigger_channel_id is None:
        return
    if after.channel.id != settings.trigger_channel_id:
        return

    channel_name = _safe_channel_name(settings.channel_name_template, member)
    try:
        temp_channel = await after.channel.clone(
            name=channel_name,
            reason=f"Temporary voice channel for {member} ({member.id})",
        )
        if temp_voice_owner_can_receive_native_manage(member, settings):
            await _grant_owner_permissions(temp_channel, member)
        await member.move_to(temp_channel)
        _recent_temp_voice_channels.add((member.guild.id, temp_channel.id))
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Failed to create temp voice channel in guild %s: %s", member.guild.id, error)
        return

    try:
        async with get_async_session() as session:
            await check_if_server_exists(member.guild, session)
            await check_if_user_exists(member, member.guild, session)
            session.add(
                VoiceChannel(
                    server_id=member.guild.id,
                    channel_id=temp_channel.id,
                    trigger_channel_id=settings.trigger_channel_id,
                    owner_user_id=member.id,
                    channel_name=temp_channel.name,
                    created_at=_naive_utcnow(),
                )
            )
            temp_log = await _create_temp_log(
                session,
                server_id=member.guild.id,
                channel_id=temp_channel.id,
                channel_name=temp_channel.name,
                trigger_channel_id=settings.trigger_channel_id,
                owner_user_id=member.id,
            )
            await _record_temp_voice_join(session, temp_log, member, temp_log.created_at)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist temp voice channel %s in guild %s", temp_channel.id, member.guild.id)
    logger.info("Temp voice channel %s created in guild %s", temp_channel.id, member.guild.id)


async def _delete_empty_temp_channel(member: discord.Member, before: discord.VoiceState, settings: ServerTempVoiceSettings) -> None:
    if before.channel is None:
        return
    if len(before.channel.members) > 0:
        return

    should_delete = False
    try:
        async with get_async_session() as session:
            active_channel = await _active_voice_channel(session, member.guild.id, before.channel.id)
            remembered_channel = (member.guild.id, before.channel.id) in _recent_temp_voice_channels
            if active_channel is None and not remembered_channel:
                return
            should_delete = True
            if active_channel is not None:
                temp_log = await _active_temp_log(session, member.guild.id, before.channel.id)
                if temp_log is None:
                    temp_log = await _create_temp_log(
                        session,
                        server_id=member.guild.id,
                        channel_id=before.channel.id,
                        channel_name=getattr(before.channel, "name", str(before.channel.id)),
                        trigger_channel_id=active_channel.trigger_channel_id or settings.trigger_channel_id or before.channel.id,
                        owner_user_id=active_channel.owner_user_id or member.id,
                    )
                temp_log.deleted_at = _naive_utcnow()
                temp_log.archive_channel_id = None
                temp_log.archive_message_id = None
                session.add(temp_log)
                decisions = (
                    await session.exec(
                        select(AIModerationDecision).where(
                            AIModerationDecision.server_id == member.guild.id,
                            AIModerationDecision.channel_id == before.channel.id,
                        )
                    )
                ).all()
                for decision in decisions:
                    decision.archive_channel_id = None
                    decision.archive_message_id = None
                    decision.updated_at = _naive_utcnow()
                    session.add(decision)
                await session.delete(active_channel)
                await session.commit()
    except Exception:
        if should_delete:
            logger.exception("Failed to finalize temp voice archive for channel %s; deleting Discord channel anyway", before.channel.id)
        else:
            logger.exception("Failed to verify temp voice channel %s before deletion", before.channel.id)
            return

    try:
        await before.channel.delete(reason="Temporary voice channel emptied.")
        _recent_temp_voice_channels.discard((member.guild.id, before.channel.id))
    except discord.NotFound:
        _recent_temp_voice_channels.discard((member.guild.id, before.channel.id))
        pass
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Failed to delete temp voice channel %s in guild %s: %s", before.channel.id, member.guild.id, error)
        return
    logger.info("Temp voice channel %s deleted in guild %s", before.channel.id, member.guild.id)

async def create_voice_channel(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.guild is None:
        return
    async with get_async_session() as session:
        settings = await session.get(ServerTempVoiceSettings, member.guild.id)
        if settings is None or not settings.enabled or settings.trigger_channel_id is None:
            return

    steps = (
        lambda: _record_temp_voice_participation(member, before, after),
        lambda: _create_temp_channel(member, after, settings),
        lambda: _delete_empty_temp_channel(member, before, settings),
    )
    for step in steps:
        try:
            await step()
        except Exception:
            logger.exception("Temp voice lifecycle step failed in guild %s", member.guild.id)
