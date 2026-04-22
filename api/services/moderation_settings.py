from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_settings import (
    ServerModerationCreateMuteRoleModel,
    ServerModerationSettingsReadModel,
    ServerModerationSettingsUpdateModel,
)
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, create_guild_role, fetch_channel, fetch_guild_roles
from api.services.moderation_core import naive_utcnow
from src.db.models import Server, ServerModerationSettings


async def get_or_create_server_moderation_settings(
    session: AsyncSession,
    server_id: int,
) -> ServerModerationSettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerModerationSettings, server_id)
    if settings:
        return settings

    settings = ServerModerationSettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


async def _resolve_role_name(server_id: int, role_id: int | None) -> str | None:
    if role_id is None:
        return None
    try:
        roles = await fetch_guild_roles(server_id)
    except Exception:
        return None

    for role in roles:
        raw_id = role.get("id")
        if raw_id is not None and str(raw_id).isdigit() and int(raw_id) == role_id:
            return role.get("name")
    return None


async def to_server_moderation_settings_read_model(
    server_id: int,
    settings: ServerModerationSettings,
) -> ServerModerationSettingsReadModel:
    role_name = await _resolve_role_name(server_id, settings.mute_role_id)
    return ServerModerationSettingsReadModel(
        server_id=str(server_id),
        mute_role_id=str(settings.mute_role_id) if settings.mute_role_id is not None else None,
        mute_role_name=role_name,
        default_mute_minutes=settings.default_mute_minutes,
        max_mute_minutes=settings.max_mute_minutes,
        auto_reconnect_voice_on_mute=settings.auto_reconnect_voice_on_mute,
        mod_log_channel_id=(
            str(settings.mod_log_channel_id) if settings.mod_log_channel_id is not None else None
        ),
        updated_at=settings.updated_at,
    )


async def update_server_moderation_settings(
    session: AsyncSession,
    server_id: int,
    body: ServerModerationSettingsUpdateModel,
) -> ServerModerationSettings:
    settings = await get_or_create_server_moderation_settings(session, server_id)

    if body.mute_role_id is not None:
        settings.mute_role_id = int(body.mute_role_id) if body.mute_role_id else None
    if body.default_mute_minutes is not None:
        settings.default_mute_minutes = body.default_mute_minutes
    if body.max_mute_minutes is not None:
        settings.max_mute_minutes = body.max_mute_minutes
    if settings.default_mute_minutes > settings.max_mute_minutes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="default_mute_minutes cannot be greater than max_mute_minutes",
        )
    if body.auto_reconnect_voice_on_mute is not None:
        settings.auto_reconnect_voice_on_mute = body.auto_reconnect_voice_on_mute
    if body.mod_log_channel_id is not None:
        if body.mod_log_channel_id:
            requested_channel_id = int(body.mod_log_channel_id)
            channel = await fetch_channel(server_id=server_id, channel_id=requested_channel_id)
            if not channel:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="mod_log_channel_id is not a channel in this server",
                )
            channel_type = channel.get("type")
            if channel_type not in TEXT_CHANNEL_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="mod_log_channel_id must be a text or announcement channel",
                )
            settings.mod_log_channel_id = requested_channel_id
        else:
            settings.mod_log_channel_id = None

    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def create_mute_role_and_attach(
    session: AsyncSession,
    server_id: int,
    body: ServerModerationCreateMuteRoleModel,
) -> ServerModerationSettings:
    role_payload = await create_guild_role(server_id=server_id, name=body.role_name)
    role_id = role_payload.get("id")
    if role_id is None or not str(role_id).isdigit():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create mute role via Discord API",
        )

    settings = await get_or_create_server_moderation_settings(session, server_id)
    settings.mute_role_id = int(role_id)
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
