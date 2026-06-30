import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_temp_voice import (
    TempVoiceArchiveAttachmentModel,
    TempVoiceArchiveDetailModel,
    TempVoiceArchiveMessageModel,
    TempVoiceArchiveSummaryModel,
    ServerTempVoiceCreateTriggerChannelModel,
    ServerTempVoiceSettingsReadModel,
    ServerTempVoiceSettingsUpdateModel,
)
from api.services.discord_guilds import create_guild_voice_channel, fetch_guild_channels
from api.services.moderation_core import naive_utcnow
from src.db.models import AttachmentLog, DeletedMessage, MessageLog, Server, ServerTempVoiceSettings, TempVoiceLog


DEFAULT_TEMP_VOICE_NAME_TEMPLATE = "{display_name}'s channel"


async def get_or_create_server_temp_voice_settings(
    session: AsyncSession,
    server_id: int,
    server_name: str | None = None,
) -> ServerTempVoiceSettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=server_name or str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerTempVoiceSettings, server_id)
    if settings:
        return settings

    settings = ServerTempVoiceSettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


def _channel_name(channels: list[dict], channel_id: int | None) -> str | None:
    if channel_id is None:
        return None
    for channel in channels:
        raw_id = channel.get("id")
        if raw_id is not None and int(raw_id) == channel_id:
            return channel.get("name")
    return None


async def to_server_temp_voice_read_model(
    server_id: int,
    settings: ServerTempVoiceSettings,
) -> ServerTempVoiceSettingsReadModel:
    try:
        channels = await fetch_guild_channels(server_id)
    except Exception:
        channels = []
    return ServerTempVoiceSettingsReadModel(
        server_id=str(server_id),
        enabled=settings.enabled,
        trigger_channel_id=str(settings.trigger_channel_id) if settings.trigger_channel_id is not None else None,
        trigger_channel_name=_channel_name(channels, settings.trigger_channel_id),
        archive_channel_id=str(settings.archive_channel_id) if settings.archive_channel_id is not None else None,
        archive_channel_name=_channel_name(channels, settings.archive_channel_id),
        archive_post_mode=settings.archive_post_mode,
        channel_name_template=settings.channel_name_template,
        owner_manage_channel_enabled=settings.owner_manage_channel_enabled,
        updated_at=settings.updated_at,
    )


async def update_server_temp_voice_settings(
    *,
    session: AsyncSession,
    server_id: int,
    body: ServerTempVoiceSettingsUpdateModel,
    server_name: str | None = None,
) -> ServerTempVoiceSettings:
    settings = await get_or_create_server_temp_voice_settings(session, server_id, server_name=server_name)

    if body.enabled is not None:
        settings.enabled = body.enabled
    if body.trigger_channel_id is not None:
        settings.trigger_channel_id = int(body.trigger_channel_id) if body.trigger_channel_id else None
    if body.archive_channel_id is not None:
        settings.archive_channel_id = int(body.archive_channel_id) if body.archive_channel_id else None
    if body.archive_post_mode is not None:
        settings.archive_post_mode = body.archive_post_mode
    if body.channel_name_template is not None:
        settings.channel_name_template = body.channel_name_template
    if body.owner_manage_channel_enabled is not None:
        settings.owner_manage_channel_enabled = body.owner_manage_channel_enabled
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


def _archive_jump_url(temp_log: TempVoiceLog) -> str | None:
    if temp_log.archive_channel_id is None or temp_log.archive_message_id is None:
        return None
    return f"https://discord.com/channels/{temp_log.server_id}/{temp_log.archive_channel_id}/{temp_log.archive_message_id}"


def _parse_deleted_attachments(raw: str | None) -> list[TempVoiceArchiveAttachmentModel]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [
        TempVoiceArchiveAttachmentModel(
            storage_key=item.get("storage_key"),
            file_name=item.get("file_name"),
            content_type=item.get("content_type"),
            deleted=True,
        )
        for item in parsed
        if isinstance(item, dict)
    ]


def _message_window_filter(temp_log: TempVoiceLog):
    filters = [
        DeletedMessage.server_id == temp_log.server_id,
        DeletedMessage.channel_id == temp_log.channel_id,
        DeletedMessage.deleted_at >= temp_log.created_at,
    ]
    if temp_log.deleted_at is not None:
        filters.append(DeletedMessage.deleted_at <= temp_log.deleted_at)
    return filters


async def _messages_for_archive(session: AsyncSession, temp_log: TempVoiceLog) -> list[MessageLog]:
    fallback_filters = [
        MessageLog.log_id.is_(None),
        MessageLog.server_id == temp_log.server_id,
        MessageLog.channel_id == temp_log.channel_id,
        MessageLog.created_at >= temp_log.created_at,
    ]
    if temp_log.deleted_at is not None:
        fallback_filters.append(MessageLog.created_at <= temp_log.deleted_at)

    return (
        await session.exec(
            select(MessageLog)
            .where(or_(MessageLog.log_id == temp_log.id, and_(*fallback_filters)))
            .order_by(MessageLog.created_at.asc(), MessageLog.message_id.asc())
        )
    ).all()


async def _deleted_messages_for_archive(session: AsyncSession, temp_log: TempVoiceLog) -> list[DeletedMessage]:
    return (
        await session.exec(
            select(DeletedMessage)
            .where(*_message_window_filter(temp_log))
            .order_by(DeletedMessage.deleted_at.asc(), DeletedMessage.message_id.asc())
        )
    ).all()


async def _attachments_by_message_id(
    session: AsyncSession,
    messages: list[MessageLog],
) -> dict[int, list[AttachmentLog]]:
    message_ids = [message.message_id for message in messages]
    if not message_ids:
        return {}
    attachment_rows = (
        await session.exec(
            select(AttachmentLog)
            .where(AttachmentLog.message_id.in_(message_ids))
            .order_by(AttachmentLog.message_id.asc(), AttachmentLog.file_name.asc())
        )
    ).all()
    attachments: dict[int, list[AttachmentLog]] = {}
    for attachment in attachment_rows:
        attachments.setdefault(attachment.message_id, []).append(attachment)
    return attachments


def _summary_from_rows(
    temp_log: TempVoiceLog,
    messages: list[MessageLog],
    deleted_messages: list[DeletedMessage],
    attachments_by_message_id: dict[int, list[AttachmentLog]],
) -> TempVoiceArchiveSummaryModel:
    deleted_attachment_count = sum(len(_parse_deleted_attachments(message.attachments_json)) for message in deleted_messages)
    return TempVoiceArchiveSummaryModel(
        id=temp_log.id,
        server_id=str(temp_log.server_id),
        channel_id=str(temp_log.channel_id),
        channel_name=temp_log.channel_name,
        trigger_channel_id=str(temp_log.trigger_channel_id) if temp_log.trigger_channel_id is not None else None,
        owner_user_id=str(temp_log.owner_user_id) if temp_log.owner_user_id is not None else None,
        created_at=temp_log.created_at,
        deleted_at=temp_log.deleted_at,
        archive_channel_id=str(temp_log.archive_channel_id) if temp_log.archive_channel_id is not None else None,
        archive_message_id=str(temp_log.archive_message_id) if temp_log.archive_message_id is not None else None,
        archive_jump_url=_archive_jump_url(temp_log),
        message_count=len(messages),
        deleted_message_count=len(deleted_messages),
        attachment_count=sum(len(items) for items in attachments_by_message_id.values()),
        deleted_attachment_count=deleted_attachment_count,
    )


async def _archive_summary(session: AsyncSession, temp_log: TempVoiceLog) -> TempVoiceArchiveSummaryModel:
    messages = await _messages_for_archive(session, temp_log)
    deleted_messages = await _deleted_messages_for_archive(session, temp_log)
    attachments_by_message_id = await _attachments_by_message_id(session, messages)
    return _summary_from_rows(temp_log, messages, deleted_messages, attachments_by_message_id)


async def list_temp_voice_archives(
    session: AsyncSession,
    server_id: int,
    include_active: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[TempVoiceArchiveSummaryModel]:
    query = select(TempVoiceLog).where(TempVoiceLog.server_id == server_id)
    if not include_active:
        query = query.where(TempVoiceLog.deleted_at.is_not(None))
    temp_logs = (
        await session.exec(
            query.order_by(TempVoiceLog.created_at.desc(), TempVoiceLog.channel_id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [await _archive_summary(session, temp_log) for temp_log in temp_logs]


async def get_temp_voice_archive_detail(
    session: AsyncSession,
    server_id: int,
    log_id: UUID,
) -> TempVoiceArchiveDetailModel:
    temp_log = await session.get(TempVoiceLog, log_id)
    if temp_log is None or temp_log.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Temporary voice archive not found")

    messages = await _messages_for_archive(session, temp_log)
    deleted_messages = await _deleted_messages_for_archive(session, temp_log)
    attachments_by_message_id = await _attachments_by_message_id(session, messages)
    summary = _summary_from_rows(temp_log, messages, deleted_messages, attachments_by_message_id)
    payload_messages: list[TempVoiceArchiveMessageModel] = []
    for message in messages:
        payload_messages.append(
            TempVoiceArchiveMessageModel(
                id=str(message.message_id),
                message_id=str(message.message_id),
                user_id=str(message.user_id),
                content=message.content,
                created_at=message.created_at,
                reply_to_message_id=str(message.reply_to_message_id) if message.reply_to_message_id is not None else None,
                attachments=[
                    TempVoiceArchiveAttachmentModel(
                        storage_key=attachment.storage_key,
                        file_name=attachment.file_name,
                        content_type=attachment.content_type,
                    )
                    for attachment in attachments_by_message_id.get(message.message_id, [])
                ],
            )
        )
    for message in deleted_messages:
        payload_messages.append(
            TempVoiceArchiveMessageModel(
                id=str(message.id),
                message_id=str(message.message_id),
                user_id=str(message.author_user_id) if message.author_user_id is not None else None,
                content=message.content,
                created_at=message.deleted_at,
                deleted_at=message.deleted_at,
                deleted=True,
                attachments=_parse_deleted_attachments(message.attachments_json),
            )
        )
    payload_messages.sort(key=lambda item: (item.created_at, item.message_id))
    return TempVoiceArchiveDetailModel(**summary.model_dump(), messages=payload_messages)


def _archive_message_line(message: TempVoiceArchiveMessageModel) -> str:
    timestamp = message.created_at.isoformat(sep=" ", timespec="seconds")
    label = "deleted " if message.deleted else ""
    content = (message.content or "").replace("\r\n", "\n").replace("\r", "\n")
    reply = f" reply_to={message.reply_to_message_id}" if message.reply_to_message_id else ""
    return f"[{timestamp}] {label}user={message.user_id or 'unknown'} message={message.message_id}{reply}\n{content}".rstrip()


async def build_temp_voice_archive_transcript(
    session: AsyncSession,
    server_id: int,
    log_id: UUID,
) -> str:
    archive = await get_temp_voice_archive_detail(session, server_id, log_id)
    lines = [
        f"Temporary voice archive: {archive.channel_name}",
        f"Server: {archive.server_id}",
        f"Channel: {archive.channel_id}",
        f"Owner: {archive.owner_user_id or 'unknown'}",
        f"Created at: {archive.created_at.isoformat(sep=' ', timespec='seconds')}",
        f"Deleted at: {(archive.deleted_at or naive_utcnow()).isoformat(sep=' ', timespec='seconds')}",
        "",
    ]
    if not archive.messages:
        lines.append("No messages were logged for this temporary voice chat.")
    for message in archive.messages:
        lines.append(_archive_message_line(message))
        for attachment in message.attachments:
            prefix = "deleted attachment" if attachment.deleted else "attachment"
            lines.append(
                f"  {prefix}: {attachment.file_name or 'attachment'} "
                f"({attachment.content_type or 'unknown'}) {attachment.storage_key or ''}".rstrip()
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


async def create_temp_voice_trigger_channel_and_attach(
    *,
    session: AsyncSession,
    server_id: int,
    body: ServerTempVoiceCreateTriggerChannelModel,
    server_name: str | None = None,
) -> ServerTempVoiceSettings:
    channel_payload = await create_guild_voice_channel(
        server_id=server_id,
        name=body.name,
        category_id=int(body.category_id) if body.category_id else None,
    )
    channel_id = channel_payload.get("id")
    if channel_id is None or not str(channel_id).isdigit():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create temp voice trigger channel via Discord API",
        )

    settings = await get_or_create_server_temp_voice_settings(session, server_id, server_name=server_name)
    settings.trigger_channel_id = int(channel_id)
    settings.enabled = body.enabled
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
