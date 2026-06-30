from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_temp_voice import (
    ServerTempVoiceCreateTriggerChannelModel,
    ServerTempVoiceSettingsReadModel,
    ServerTempVoiceSettingsUpdateModel,
)
from api.services.discord_guilds import create_guild_voice_channel, fetch_guild_channels
from api.services.moderation_core import naive_utcnow
from src.db.models import Server, ServerTempVoiceSettings


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
    if body.channel_name_template is not None:
        settings.channel_name_template = body.channel_name_template
    if body.owner_manage_channel_enabled is not None:
        settings.owner_manage_channel_enabled = body.owner_manage_channel_enabled
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


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
