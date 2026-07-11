from datetime import timedelta

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.monitoring import MonitoredUserReadModel
from api.models.server_security import (
    ServerSecurityCreateNewcomerRoleModel,
    ServerSecurityLockdownUpdateModel,
    ServerSecurityNewcomerActionModel,
    ServerSecurityNewcomerRoleUpdateModel,
    ServerSecurityPermissionsUpdateModel,
    ServerSecurityRoleSuggestionModel,
    ServerSecuritySettingsReadModel,
    ServerSecurityVerifiedRoleUpdateModel,
)
from api.services.discord_guilds import (
    TEXT_CHANNEL_TYPES,
    add_guild_member_role,
    create_guild_role,
    fetch_guild_roles,
    fetch_guild_channels,
    remove_guild_member_role,
    update_guild_role_permissions,
    update_channel_slowmode,
)
from api.services.moderation_core import naive_utcnow
from api.services.monitoring_service import update_monitored_user, upsert_monitored_user
from src.db.models import MonitoredUser, Server, ServerSecuritySettings


async def get_or_create_server_security_settings(
    session: AsyncSession,
    server_id: int,
    server_name: str | None = None,
) -> ServerSecuritySettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=server_name or str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerSecuritySettings, server_id)
    if settings:
        return settings

    settings = ServerSecuritySettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


async def _resolve_role_name_and_permissions(server_id: int, role_id: int | None) -> tuple[str | None, int | None]:
    if role_id is None:
        return None, None
    try:
        roles = await fetch_guild_roles(server_id)
    except Exception:
        return None, None

    for role in roles:
        raw_id = role.get("id")
        if raw_id is not None and int(raw_id) == role_id:
            raw_permissions = role.get("permissions")
            return role.get("name"), int(raw_permissions) if raw_permissions is not None else None
    return None, None


async def to_server_security_read_model(
    server_id: int,
    settings: ServerSecuritySettings,
) -> ServerSecuritySettingsReadModel:
    role_name, _ = await _resolve_role_name_and_permissions(server_id, settings.verified_role_id)
    newcomer_role_name, _ = await _resolve_role_name_and_permissions(server_id, settings.newcomer_role_id)
    return ServerSecuritySettingsReadModel(
        server_id=str(server_id),
        verified_role_id=str(settings.verified_role_id) if settings.verified_role_id is not None else None,
        verified_role_name=role_name,
        newcomer_role_id=str(settings.newcomer_role_id) if settings.newcomer_role_id is not None else None,
        newcomer_role_name=newcomer_role_name,
        newcomer_restriction_enabled=settings.newcomer_restriction_enabled,
        newcomer_auto_release_minutes=settings.newcomer_auto_release_minutes,
        normal_permissions=(
            str(settings.normal_permissions) if settings.normal_permissions is not None else None
        ),
        lockdown_permissions=(
            str(settings.lockdown_permissions) if settings.lockdown_permissions is not None else None
        ),
        lockdown_enabled=settings.lockdown_enabled,
        public_bot_responses_paused=settings.public_bot_responses_paused,
        role_mutations_paused=settings.role_mutations_paused,
        lockdown_slowmode_seconds=settings.lockdown_slowmode_seconds,
        lockdown_slowmode_channel_ids=list(settings.lockdown_slowmode_channel_ids or []),
        updated_at=settings.updated_at,
    )


async def update_verified_role(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityVerifiedRoleUpdateModel,
    server_name: str | None = None,
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id, server_name=server_name)

    if not body.role_id:
        settings.verified_role_id = None
        settings.updated_at = naive_utcnow()
        session.add(settings)
        await session.flush()
        await session.refresh(settings)
        return settings

    role_id = int(body.role_id)
    _, current_permissions = await _resolve_role_name_and_permissions(server_id, role_id)
    settings.verified_role_id = role_id
    if settings.normal_permissions is None and current_permissions is not None:
        settings.normal_permissions = current_permissions
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


def build_newcomer_role_suggestion() -> ServerSecurityRoleSuggestionModel:
    return ServerSecurityRoleSuggestionModel(
        purpose="newcomer_restricted_role",
        role_name="Newcomer",
        permissions="0",
        mentionable=False,
        hoist=False,
        color=0xF2C94C,
        reason=(
            "Recommended for restricted newcomers: no base permissions, not mentionable, "
            "not displayed separately. Channel overwrites can then decide exactly what newcomers can do."
        ),
    )


async def update_newcomer_role(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityNewcomerRoleUpdateModel,
    server_name: str | None = None,
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id, server_name=server_name)

    if body.role_id is not None:
        settings.newcomer_role_id = int(body.role_id) if body.role_id else None
    if body.enabled is not None:
        settings.newcomer_restriction_enabled = body.enabled
    if body.auto_release_minutes is not None:
        settings.newcomer_auto_release_minutes = (
            body.auto_release_minutes if body.auto_release_minutes > 0 else None
        )
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def create_newcomer_role_and_attach(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityCreateNewcomerRoleModel,
    server_name: str | None = None,
) -> ServerSecuritySettings:
    role_payload = await create_guild_role(
        server_id=server_id,
        name=body.role_name,
        permissions=body.permissions,
        mentionable=body.mentionable,
        hoist=body.hoist,
        color=body.color,
    )
    role_id = role_payload.get("id")
    if role_id is None or not str(role_id).isdigit():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create newcomer role via Discord API",
        )

    settings = await get_or_create_server_security_settings(session, server_id, server_name=server_name)
    settings.newcomer_role_id = int(role_id)
    settings.newcomer_restriction_enabled = body.enabled
    settings.newcomer_auto_release_minutes = (
        body.auto_release_minutes if body.auto_release_minutes and body.auto_release_minutes > 0 else None
    )
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def apply_newcomer_member_action(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    body: ServerSecurityNewcomerActionModel,
    actor_user_id: int,
) -> MonitoredUserReadModel:
    settings = await get_or_create_server_security_settings(session, server_id)
    if settings.newcomer_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="newcomer_role_id is not configured",
        )

    item = (
        await session.exec(
            select(MonitoredUser).where(
                MonitoredUser.server_id == server_id,
                MonitoredUser.user_id == user_id,
                MonitoredUser.source == "newcomer",
            )
        )
    ).first()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="newcomer restriction not found")

    reason = body.reason or {
        "release": "Released manually from newcomer restrictions",
        "reapply": "Newcomer restrictions reapplied manually",
        "extend": "Newcomer restriction extended manually",
    }[body.action]

    if body.action == "release":
        await remove_guild_member_role(server_id, user_id, settings.newcomer_role_id)
        return await update_monitored_user(
            session=session,
            server_id=server_id,
            user_id=user_id,
            reason=reason,
            is_active=False,
            updated_by_user_id=actor_user_id,
        )

    duration_minutes = body.duration_minutes or settings.newcomer_auto_release_minutes
    if body.action == "extend" and duration_minutes is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="duration_minutes is required when no default release duration is configured",
        )
    release_due_at = (
        naive_utcnow() + timedelta(minutes=duration_minutes)
        if duration_minutes
        else None
    )
    await add_guild_member_role(server_id, user_id, settings.newcomer_role_id)
    return await upsert_monitored_user(
        session=session,
        server_id=server_id,
        user_id=user_id,
        reason=reason,
        added_by_user_id=actor_user_id,
        source="newcomer",
        release_due_at=release_due_at,
    )


async def update_permission_templates(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityPermissionsUpdateModel,
    server_name: str | None = None,
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id, server_name=server_name)

    if body.normal_permissions is not None:
        settings.normal_permissions = int(body.normal_permissions) if body.normal_permissions else None
    if body.lockdown_permissions is not None:
        settings.lockdown_permissions = int(body.lockdown_permissions) if body.lockdown_permissions else None
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def apply_lockdown_state(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityLockdownUpdateModel,
    server_name: str | None = None,
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id, server_name=server_name)
    if settings.verified_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="verified_role_id is not configured",
        )

    permission_value = settings.lockdown_permissions if body.enabled else settings.normal_permissions
    if permission_value is None:
        template_name = "lockdown_permissions" if body.enabled else "normal_permissions"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{template_name} is not configured",
        )

    channels = {str(channel.get("id")): channel for channel in await fetch_guild_channels(server_id)}
    slowmode_seconds = body.slowmode_seconds or 0
    requested_channel_ids = list(body.channel_ids)
    if body.enabled and slowmode_seconds > 0 and not requested_channel_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="channel_ids cannot be empty when slowmode is enabled",
        )
    invalid_channels = [
        channel_id
        for channel_id in requested_channel_ids
        if channel_id not in channels or channels[channel_id].get("type") not in TEXT_CHANNEL_TYPES
    ]
    if invalid_channels:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid text channels: {', '.join(invalid_channels[:5])}",
        )

    await update_guild_role_permissions(
        server_id=server_id,
        role_id=settings.verified_role_id,
        permissions=permission_value,
        bypass_security_pause=True,
    )

    applied_channels: list[str] = []
    previous = {
        channel_id: int(channels[channel_id].get("rate_limit_per_user") or 0)
        for channel_id in requested_channel_ids
    }
    try:
        if body.enabled:
            for channel_id in requested_channel_ids:
                await update_channel_slowmode(int(channel_id), slowmode_seconds)
                applied_channels.append(channel_id)
            settings.lockdown_slowmode_previous = previous
            settings.lockdown_slowmode_channel_ids = requested_channel_ids
            settings.lockdown_slowmode_seconds = slowmode_seconds or None
            settings.public_bot_responses_paused = body.pause_public_responses
            settings.role_mutations_paused = body.pause_role_mutations
        else:
            for channel_id, previous_seconds in (settings.lockdown_slowmode_previous or {}).items():
                await update_channel_slowmode(int(channel_id), int(previous_seconds))
            settings.lockdown_slowmode_previous = {}
            settings.lockdown_slowmode_channel_ids = []
            settings.lockdown_slowmode_seconds = None
            settings.public_bot_responses_paused = False
            settings.role_mutations_paused = False
    except Exception:
        if body.enabled:
            for channel_id in reversed(applied_channels):
                await update_channel_slowmode(int(channel_id), int(previous.get(channel_id, 0)))
            if settings.normal_permissions is not None:
                await update_guild_role_permissions(
                    server_id=server_id,
                    role_id=settings.verified_role_id,
                    permissions=settings.normal_permissions,
                    bypass_security_pause=True,
                )
        raise

    settings.lockdown_enabled = body.enabled
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
