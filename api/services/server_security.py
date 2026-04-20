from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_security import (
    ServerSecurityLockdownUpdateModel,
    ServerSecurityPermissionsUpdateModel,
    ServerSecuritySettingsReadModel,
    ServerSecurityVerifiedRoleUpdateModel,
)
from api.services.discord_guilds import fetch_guild_roles, update_guild_role_permissions
from api.services.moderation_core import naive_utcnow
from src.db.models import Server, ServerSecuritySettings


async def get_or_create_server_security_settings(session: AsyncSession, server_id: int) -> ServerSecuritySettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=str(server_id))
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
    return ServerSecuritySettingsReadModel(
        server_id=str(server_id),
        verified_role_id=str(settings.verified_role_id) if settings.verified_role_id is not None else None,
        verified_role_name=role_name,
        normal_permissions=(
            str(settings.normal_permissions) if settings.normal_permissions is not None else None
        ),
        lockdown_permissions=(
            str(settings.lockdown_permissions) if settings.lockdown_permissions is not None else None
        ),
        lockdown_enabled=settings.lockdown_enabled,
        updated_at=settings.updated_at,
    )


async def update_verified_role(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityVerifiedRoleUpdateModel,
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id)

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


async def update_permission_templates(
    session: AsyncSession,
    server_id: int,
    body: ServerSecurityPermissionsUpdateModel,
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id)

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
) -> ServerSecuritySettings:
    settings = await get_or_create_server_security_settings(session, server_id)
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

    await update_guild_role_permissions(
        server_id=server_id,
        role_id=settings.verified_role_id,
        permissions=permission_value,
    )

    settings.lockdown_enabled = body.enabled
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
