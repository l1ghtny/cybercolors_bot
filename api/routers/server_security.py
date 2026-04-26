from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_admin_or_owner, require_server_dashboard_access
from api.models.server_security import (
    ServerSecurityLockdownUpdateModel,
    ServerSecurityPermissionsUpdateModel,
    ServerSecuritySettingsReadModel,
    ServerSecurityVerifiedRoleUpdateModel,
)
from api.services.server_security import (
    apply_lockdown_state,
    get_or_create_server_security_settings,
    to_server_security_read_model,
    update_permission_templates,
    update_verified_role,
)
from src.db.database import get_session

server_security_router = APIRouter(
    prefix="/servers/{server_id}/security",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_security_router.get("", response_model=ServerSecuritySettingsReadModel)
async def get_server_security_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    settings = await get_or_create_server_security_settings(session, server_id)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.put("/verified-role", response_model=ServerSecuritySettingsReadModel)
async def set_server_verified_role(
    server_id: int,
    body: ServerSecurityVerifiedRoleUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_server_admin_or_owner),
):
    settings = await update_verified_role(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.put("/permissions", response_model=ServerSecuritySettingsReadModel)
async def set_server_security_permissions(
    server_id: int,
    body: ServerSecurityPermissionsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_server_admin_or_owner),
):
    settings = await update_permission_templates(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.put("/lockdown", response_model=ServerSecuritySettingsReadModel)
async def set_server_lockdown_state(
    server_id: int,
    body: ServerSecurityLockdownUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_server_admin_or_owner),
):
    settings = await apply_lockdown_state(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)
