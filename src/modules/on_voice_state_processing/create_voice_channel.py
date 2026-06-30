from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import discord
from sqlmodel import select

from src.db.database import get_async_session
from src.db.models import (
    AIModerationDecision,
    AttachmentLog,
    DeletedMessage,
    MessageLog,
    ServerModerationSettings,
    ServerTempVoiceSettings,
    TempVoiceLog,
    VoiceChannel,
)
from src.modules.logs_setup import logger
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

logger = logger.logging.getLogger("bot")


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_channel_name(template: str, member: discord.Member) -> str:
    display_name = (getattr(member, "display_name", None) or getattr(member, "name", None) or str(member.id)).strip()
    username = (getattr(member, "name", None) or display_name).strip()
    channel_name = template.format(display_name=display_name, username=username)
    channel_name = " ".join(channel_name.split())
    return (channel_name or f"{display_name}'s channel")[:100]


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
        if settings.owner_manage_channel_enabled:
            await _grant_owner_permissions(temp_channel, member)
        await member.move_to(temp_channel)
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Failed to create temp voice channel in guild %s: %s", member.guild.id, error)
        return

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
        await _create_temp_log(
            session,
            server_id=member.guild.id,
            channel_id=temp_channel.id,
            channel_name=temp_channel.name,
            trigger_channel_id=settings.trigger_channel_id,
            owner_user_id=member.id,
        )
        await session.commit()
    logger.info("Temp voice channel %s created in guild %s", temp_channel.id, member.guild.id)


def _message_line(message: MessageLog) -> str:
    timestamp = message.created_at.isoformat(sep=" ", timespec="seconds")
    content = (message.content or "").replace("\r\n", "\n").replace("\r", "\n")
    reply = f" reply_to={message.reply_to_message_id}" if message.reply_to_message_id else ""
    return f"[{timestamp}] user={message.user_id} message={message.message_id}{reply}\n{content}".rstrip()


def _deleted_message_line(message: DeletedMessage) -> str:
    timestamp = message.deleted_at.isoformat(sep=" ", timespec="seconds")
    content = (message.content or "").replace("\r\n", "\n").replace("\r", "\n")
    return f"[{timestamp}] deleted user={message.author_user_id or 'unknown'} message={message.message_id}\n{content}".rstrip()


async def _transcript_text(session, temp_log: TempVoiceLog) -> str:
    messages = (
        await session.exec(
            select(MessageLog)
            .where(
                MessageLog.server_id == temp_log.server_id,
                MessageLog.channel_id == temp_log.channel_id,
            )
            .order_by(MessageLog.created_at.asc(), MessageLog.message_id.asc())
        )
    ).all()
    deleted_messages = (
        await session.exec(
            select(DeletedMessage)
            .where(
                DeletedMessage.server_id == temp_log.server_id,
                DeletedMessage.channel_id == temp_log.channel_id,
            )
            .order_by(DeletedMessage.deleted_at.asc(), DeletedMessage.message_id.asc())
        )
    ).all()
    if not messages and not deleted_messages:
        return "No messages were logged for this temporary voice chat."

    message_ids = [message.message_id for message in messages]
    attachment_rows = (
        await session.exec(
            select(AttachmentLog)
            .where(AttachmentLog.message_id.in_(message_ids))
            .order_by(AttachmentLog.message_id.asc(), AttachmentLog.file_name.asc())
        )
    ).all()
    attachments_by_message_id: dict[int, list[AttachmentLog]] = {}
    for attachment in attachment_rows:
        attachments_by_message_id.setdefault(attachment.message_id, []).append(attachment)

    lines = [
        f"Temporary voice archive: {temp_log.channel_name}",
        f"Server: {temp_log.server_id}",
        f"Channel: {temp_log.channel_id}",
        f"Owner: {temp_log.owner_user_id or 'unknown'}",
        f"Created at: {temp_log.created_at.isoformat(sep=' ', timespec='seconds')}",
        f"Deleted at: {(temp_log.deleted_at or _naive_utcnow()).isoformat(sep=' ', timespec='seconds')}",
        "",
    ]
    for message in messages:
        lines.append(_message_line(message))
        for attachment in attachments_by_message_id.get(message.message_id, []):
            lines.append(f"  attachment: {attachment.file_name} ({attachment.content_type}) {attachment.storage_key}")
        lines.append("")
    for message in deleted_messages:
        lines.append(_deleted_message_line(message))
        if message.attachments_json:
            try:
                deleted_attachments = json.loads(message.attachments_json)
            except json.JSONDecodeError:
                deleted_attachments = []
            for attachment in deleted_attachments if isinstance(deleted_attachments, list) else []:
                if not isinstance(attachment, dict):
                    continue
                lines.append(
                    "  deleted attachment: "
                    f"{attachment.get('file_name') or 'attachment'} "
                    f"({attachment.get('content_type') or 'unknown'}) "
                    f"{attachment.get('storage_key') or ''}".rstrip()
                )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _archive_embed(temp_log: TempVoiceLog, message_count: int) -> discord.Embed:
    embed = discord.Embed(
        title="Temporary voice chat archived",
        description=f"Archive for deleted channel `{temp_log.channel_name}` (`{temp_log.channel_id}`).",
        color=discord.Color.blurple(),
        timestamp=temp_log.deleted_at or _naive_utcnow(),
    )
    embed.add_field(name="Owner", value=f"<@{temp_log.owner_user_id}> (`{temp_log.owner_user_id}`)" if temp_log.owner_user_id else "`unknown`", inline=True)
    embed.add_field(name="Messages", value=f"`{message_count}`", inline=True)
    embed.add_field(name="Created", value=f"`{temp_log.created_at.isoformat(sep=' ', timespec='seconds')}`", inline=False)
    return embed


async def _archive_channel_chat(
    guild: discord.Guild,
    temp_log: TempVoiceLog,
    settings: ServerTempVoiceSettings,
) -> tuple[int | None, int | None]:
    async with get_async_session() as session:
        mod_settings = await session.get(ServerModerationSettings, guild.id)
        archive_channel_id = settings.archive_channel_id or (mod_settings.mod_log_channel_id if mod_settings else None)
        if archive_channel_id is None:
            return None, None
        transcript = await _transcript_text(session, temp_log)
        current_messages = (
            await session.exec(
                select(MessageLog).where(
                    MessageLog.server_id == temp_log.server_id,
                    MessageLog.channel_id == temp_log.channel_id,
                )
            )
        ).all()
        deleted_messages = (
            await session.exec(
                select(DeletedMessage).where(
                    DeletedMessage.server_id == temp_log.server_id,
                    DeletedMessage.channel_id == temp_log.channel_id,
                )
            )
        ).all()

    archive_channel = guild.get_channel(archive_channel_id)
    if archive_channel is None:
        try:
            archive_channel = await guild.fetch_channel(archive_channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            logger.warning("Cannot resolve temp voice archive channel %s in guild %s: %s", archive_channel_id, guild.id, error)
            return archive_channel_id, None
    send = getattr(archive_channel, "send", None)
    if send is None:
        return archive_channel_id, None

    filename = f"temp-voice-{temp_log.channel_id}.txt"
    file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=filename)
    try:
        archive_message = await send(
            embed=_archive_embed(temp_log, len(current_messages) + len(deleted_messages)),
            file=file,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Failed to publish temp voice archive for channel %s: %s", temp_log.channel_id, error)
        return archive_channel_id, None
    return archive_channel_id, getattr(archive_message, "id", None)


async def _update_ai_review_archive_notice(
    guild: discord.Guild,
    *,
    review_channel_id: int | None,
    review_message_id: int | None,
    archive_channel_id: int | None,
    archive_message_id: int | None,
) -> None:
    if not review_channel_id or not review_message_id or not archive_channel_id or not archive_message_id:
        return
    review_channel = guild.get_channel(review_channel_id)
    if review_channel is None:
        try:
            review_channel = await guild.fetch_channel(review_channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return
    fetch_message = getattr(review_channel, "fetch_message", None)
    if fetch_message is None:
        return
    try:
        review_message = await fetch_message(review_message_id)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return
    embeds = list(getattr(review_message, "embeds", []) or [])
    if not embeds:
        return
    embed = embeds[0].copy()
    if any(field.name == "Original channel deleted" for field in embed.fields):
        return
    archive_url = f"https://discord.com/channels/{guild.id}/{archive_channel_id}/{archive_message_id}"
    embed.add_field(
        name="Original channel deleted",
        value=f"The source channel was deleted. [Open transcript archive]({archive_url}).",
        inline=False,
    )
    embeds[0] = embed
    try:
        await review_message.edit(embeds=embeds)
    except (discord.Forbidden, discord.HTTPException):
        return


async def _delete_empty_temp_channel(member: discord.Member, before: discord.VoiceState, settings: ServerTempVoiceSettings) -> None:
    if before.channel is None:
        return
    if len(before.channel.members) > 0:
        return

    async with get_async_session() as session:
        active_channel = await _active_voice_channel(session, member.guild.id, before.channel.id)
        if active_channel is None:
            return
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
        session.add(temp_log)
        await session.commit()
        await session.refresh(temp_log)

    archive_channel_id, archive_message_id = await _archive_channel_chat(member.guild, temp_log, settings)
    review_refs: list[tuple[int | None, int | None]] = []

    async with get_async_session() as session:
        active_channel = await _active_voice_channel(session, member.guild.id, before.channel.id)
        temp_log = await _active_temp_log(session, member.guild.id, before.channel.id)
        if temp_log is None:
            temp_log = (
                await session.exec(
                    select(TempVoiceLog)
                    .where(TempVoiceLog.server_id == member.guild.id, TempVoiceLog.channel_id == before.channel.id)
                    .order_by(TempVoiceLog.created_at.desc())
                )
            ).first()
        if temp_log is not None:
            temp_log.archive_channel_id = archive_channel_id
            temp_log.archive_message_id = archive_message_id
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
                decision.archive_channel_id = archive_channel_id
                decision.archive_message_id = archive_message_id
                decision.updated_at = _naive_utcnow()
                review_refs.append((decision.review_channel_id, decision.review_message_id))
                session.add(decision)
        if active_channel is not None:
            await session.delete(active_channel)
        await session.commit()

    for review_channel_id, review_message_id in review_refs:
        await _update_ai_review_archive_notice(
            member.guild,
            review_channel_id=review_channel_id,
            review_message_id=review_message_id,
            archive_channel_id=archive_channel_id,
            archive_message_id=archive_message_id,
        )

    try:
        await before.channel.delete(reason="Temporary voice channel emptied.")
    except discord.NotFound:
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

    await _create_temp_channel(member, after, settings)
    await _delete_empty_temp_channel(member, before, settings)
