from __future__ import annotations

from uuid import UUID

import discord

from api.services.monitoring_service import (
    get_monitoring_notification_channel_id,
    mark_monitoring_activity_notification_sent,
    maybe_auto_monitor_new_member,
    record_monitored_user_activity,
)
from src.db.database import get_async_session
from src.modules.localization.service import get_server_locale
from src.modules.logs_setup import logger
from src.modules.moderation.mod_log import build_monitoring_activity_log_embed, send_mod_log_message

logger = logger.logging.getLogger("bot")

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = (getattr(attachment, "content_type", None) or "").lower()
    if content_type.startswith("image/"):
        return True
    filename = (getattr(attachment, "filename", None) or "").lower()
    return any(filename.endswith(ext) for ext in _IMAGE_EXTENSIONS)


def _message_metadata(message: discord.Message) -> dict:
    attachments = [
        {
            "id": str(getattr(attachment, "id", "")),
            "filename": getattr(attachment, "filename", None),
            "content_type": getattr(attachment, "content_type", None),
            "url": getattr(attachment, "url", None),
            "is_image": _is_image_attachment(attachment),
        }
        for attachment in getattr(message, "attachments", [])
    ]
    return {
        "attachments": attachments,
        "jump_url": getattr(message, "jump_url", None),
        "reply_to_message_id": str(message.reference.message_id) if message.reference and message.reference.message_id else None,
    }


async def _mark_notification_sent(event_id: UUID) -> None:
    async with get_async_session() as session:
        await mark_monitoring_activity_notification_sent(session, event_id)
        await session.commit()


async def _send_event_notification(
    guild: discord.Guild,
    *,
    event,
    channel_id: int | None,
    locale: str | None,
) -> None:
    if not channel_id:
        return
    member = guild.get_member(event.user_id)
    display_name = member.display_name if member else str(event.user_id)
    embed = build_monitoring_activity_log_embed(
        server_id=guild.id,
        event_type=event.event_type,
        user_id=event.user_id,
        user_display=display_name,
        channel_id=event.channel_id,
        message_id=event.message_id,
        message_content=event.message_content,
        metadata=event.metadata_json or {},
        locale=locale,
    )
    sent = await send_mod_log_message(guild, channel_id, embed=embed)
    if sent:
        await _mark_notification_sent(event.id)


async def record_message_activity(message: discord.Message) -> None:
    if message.guild is None or getattr(message.author, "bot", False):
        return
    metadata = _message_metadata(message)
    async with get_async_session() as session:
        event, should_notify = await record_monitored_user_activity(
            session,
            server_id=message.guild.id,
            user_id=message.author.id,
            event_type="message",
            channel_id=message.channel.id,
            message_id=message.id,
            message_content=(message.content or "")[:4000],
            metadata=metadata,
        )
        notification_channel_id = await get_monitoring_notification_channel_id(session, message.guild.id) if should_notify else None
        image_events = []
        if any(item.get("is_image") for item in metadata.get("attachments", [])):
            image_event, image_should_notify = await record_monitored_user_activity(
                session,
                server_id=message.guild.id,
                user_id=message.author.id,
                event_type="image",
                channel_id=message.channel.id,
                message_id=message.id,
                message_content=(message.content or "")[:4000],
                metadata=metadata,
            )
            image_channel_id = await get_monitoring_notification_channel_id(session, message.guild.id) if image_should_notify else None
            if image_event is not None and image_channel_id:
                image_events.append((image_event, image_channel_id))
        await session.commit()

    locale = await get_server_locale(message.guild.id)
    if event is not None and notification_channel_id:
        await _send_event_notification(message.guild, event=event, channel_id=notification_channel_id, locale=locale)
    for image_event, image_channel_id in image_events:
        await _send_event_notification(message.guild, event=image_event, channel_id=image_channel_id, locale=locale)


async def record_voice_join_activity(member: discord.Member, after: discord.VoiceState) -> None:
    if member.guild is None or member.bot or after.channel is None:
        return
    async with get_async_session() as session:
        event, should_notify = await record_monitored_user_activity(
            session,
            server_id=member.guild.id,
            user_id=member.id,
            event_type="voice_join",
            channel_id=after.channel.id,
            metadata={"channel_name": getattr(after.channel, "name", None)},
        )
        notification_channel_id = await get_monitoring_notification_channel_id(session, member.guild.id) if should_notify else None
        await session.commit()
    if event is not None and notification_channel_id:
        locale = await get_server_locale(member.guild.id)
        await _send_event_notification(member.guild, event=event, channel_id=notification_channel_id, locale=locale)


async def record_thread_create_activity(thread: discord.Thread) -> None:
    guild = thread.guild
    owner_id = thread.owner_id
    if guild is None or owner_id is None:
        return
    async with get_async_session() as session:
        event, should_notify = await record_monitored_user_activity(
            session,
            server_id=guild.id,
            user_id=owner_id,
            event_type="thread_create",
            channel_id=thread.parent_id,
            message_id=thread.id,
            metadata={"thread_id": str(thread.id), "thread_name": thread.name},
        )
        notification_channel_id = await get_monitoring_notification_channel_id(session, guild.id) if should_notify else None
        await session.commit()
    if event is not None and notification_channel_id:
        locale = await get_server_locale(guild.id)
        await _send_event_notification(guild, event=event, channel_id=notification_channel_id, locale=locale)


async def record_bot_command_activity(interaction: discord.Interaction) -> None:
    if (
        interaction.guild is None
        or interaction.user is None
        or getattr(interaction.user, "bot", False)
        or interaction.command is None
    ):
        return
    async with get_async_session() as session:
        event, should_notify = await record_monitored_user_activity(
            session,
            server_id=interaction.guild.id,
            user_id=interaction.user.id,
            event_type="bot_command",
            channel_id=interaction.channel_id,
            metadata={"command_name": interaction.command.name},
        )
        notification_channel_id = await get_monitoring_notification_channel_id(session, interaction.guild.id) if should_notify else None
        await session.commit()
    if event is not None and notification_channel_id:
        locale = await get_server_locale(interaction.guild.id)
        await _send_event_notification(interaction.guild, event=event, channel_id=notification_channel_id, locale=locale)


async def record_ai_conversation_activity(message: discord.Message) -> None:
    if message.guild is None or getattr(message.author, "bot", False):
        return
    metadata = _message_metadata(message)
    async with get_async_session() as session:
        event, should_notify = await record_monitored_user_activity(
            session,
            server_id=message.guild.id,
            user_id=message.author.id,
            event_type="ai_interaction",
            channel_id=message.channel.id,
            message_id=message.id,
            message_content=(message.content or "")[:4000],
            metadata=metadata,
        )
        notification_channel_id = await get_monitoring_notification_channel_id(session, message.guild.id) if should_notify else None
        await session.commit()
    if event is not None and notification_channel_id:
        locale = await get_server_locale(message.guild.id)
        await _send_event_notification(message.guild, event=event, channel_id=notification_channel_id, locale=locale)


async def handle_member_join_monitoring(member: discord.Member) -> None:
    if member.guild is None or member.bot:
        return
    async with get_async_session() as session:
        auto_added = await maybe_auto_monitor_new_member(session, member=member)
        event_type = "auto_monitor" if auto_added is not None else "rejoin"
        event, should_notify = await record_monitored_user_activity(
            session,
            server_id=member.guild.id,
            user_id=member.id,
            event_type=event_type,
            metadata={"reason": auto_added.reason if auto_added else None},
        )
        notification_channel_id = await get_monitoring_notification_channel_id(session, member.guild.id) if (should_notify or auto_added) else None
        await session.commit()
    if event is not None and notification_channel_id:
        locale = await get_server_locale(member.guild.id)
        await _send_event_notification(member.guild, event=event, channel_id=notification_channel_id, locale=locale)
