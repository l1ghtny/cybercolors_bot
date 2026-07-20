from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.dependencies.current_user import get_current_discord_user_id
from api.models.monitoring import MonitoredUserReadModel
from api.models.server_security import (
    ServerSecurityCreateNewcomerRoleModel,
    ServerSecurityIncidentActionsUpdateModel,
    ServerSecurityLockdownUpdateModel,
    ServerSecurityNewcomerActionModel,
    ServerSecurityNewcomerRestrictionApplyResult,
    ServerSecurityNewcomerRoleUpdateModel,
    ServerSecurityPermissionsUpdateModel,
    ServerSecurityRoleSuggestionModel,
    ServerSecuritySettingsReadModel,
    ServerSecurityVerifiedRoleUpdateModel,
)
from api.services.server_security import (
    apply_lockdown_state,
    apply_incident_actions,
    apply_newcomer_restrictions,
    build_newcomer_role_suggestion,
    apply_newcomer_member_action,
    create_newcomer_role_and_attach,
    get_or_create_server_security_settings,
    to_server_security_read_model,
    update_newcomer_role,
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
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    settings = await update_verified_role(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.get("/newcomer-role/suggestion", response_model=ServerSecurityRoleSuggestionModel)
async def get_newcomer_role_suggestion(
    server_id: int,
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    return build_newcomer_role_suggestion()


@server_security_router.put("/newcomer-role", response_model=ServerSecuritySettingsReadModel)
async def set_server_newcomer_role(
    server_id: int,
    body: ServerSecurityNewcomerRoleUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    settings = await update_newcomer_role(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.post("/newcomer-role/create", response_model=ServerSecuritySettingsReadModel)
async def create_server_newcomer_role(
    server_id: int,
    body: ServerSecurityCreateNewcomerRoleModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    settings = await create_newcomer_role_and_attach(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.post(
    "/newcomer-role/apply-restrictions",
    response_model=ServerSecurityNewcomerRestrictionApplyResult,
)
async def apply_server_newcomer_restrictions(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    return await apply_newcomer_restrictions(session=session, server_id=server_id)


@server_security_router.post(
    "/newcomers/{user_id}/action",
    response_model=MonitoredUserReadModel,
)
async def act_on_server_newcomer(
    server_id: int,
    user_id: int,
    body: ServerSecurityNewcomerActionModel,
    session: AsyncSession = Depends(get_session),
    actor_user_id: int = Depends(get_current_discord_user_id),
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    return await apply_newcomer_member_action(
        session=session,
        server_id=server_id,
        user_id=user_id,
        body=body,
        actor_user_id=actor_user_id,
    )


@server_security_router.put("/permissions", response_model=ServerSecuritySettingsReadModel)
async def set_server_security_permissions(
    server_id: int,
    body: ServerSecurityPermissionsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("security.settings.edit")),
):
    settings = await update_permission_templates(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.put("/lockdown", response_model=ServerSecuritySettingsReadModel)
async def set_server_lockdown_state(
    server_id: int,
    body: ServerSecurityLockdownUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("security.lockdown.manage")),
):
    settings = await apply_lockdown_state(session=session, server_id=server_id, body=body)
    return await to_server_security_read_model(server_id, settings)


@server_security_router.put("/incident-actions", response_model=ServerSecuritySettingsReadModel)
async def set_server_incident_actions(
    server_id: int,
    body: ServerSecurityIncidentActionsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("security.lockdown.manage")),
):
    await apply_incident_actions(server_id=server_id, body=body)
    settings = await get_or_create_server_security_settings(session, server_id)
    return await to_server_security_read_model(server_id, settings)
