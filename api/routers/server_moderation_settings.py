from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.moderation_settings import (
    ServerModerationCreateMuteRoleModel,
    ServerModerationSettingsReadModel,
    ServerModerationSettingsTestResultModel,
    ServerModerationSettingsUpdateModel,
)
from api.services.moderation_settings import (
    check_mod_log_setting,
    check_mute_role_setting,
    create_mute_role_and_attach,
    get_or_create_server_moderation_settings,
    to_server_moderation_settings_read_model,
    update_server_moderation_settings,
)
from src.db.database import get_session

server_moderation_settings_router = APIRouter(
    prefix="/servers/{server_id}/moderation-settings",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_moderation_settings_router.get("", response_model=ServerModerationSettingsReadModel)
async def get_server_moderation_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    settings = await get_or_create_server_moderation_settings(session, server_id)
    return await to_server_moderation_settings_read_model(server_id, settings)


@server_moderation_settings_router.put("", response_model=ServerModerationSettingsReadModel)
async def set_server_moderation_settings(
    server_id: int,
    body: ServerModerationSettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("moderation.settings.edit")),
):
    settings = await update_server_moderation_settings(session=session, server_id=server_id, body=body)
    return await to_server_moderation_settings_read_model(server_id, settings)


@server_moderation_settings_router.post(
    "/create-mute-role",
    response_model=ServerModerationSettingsReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def create_server_mute_role(
    server_id: int,
    body: ServerModerationCreateMuteRoleModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("moderation.settings.edit")),
):
    settings = await create_mute_role_and_attach(session=session, server_id=server_id, body=body)
    return await to_server_moderation_settings_read_model(server_id, settings)


@server_moderation_settings_router.post(
    "/test-mute-role",
    response_model=ServerModerationSettingsTestResultModel,
)
async def test_server_mute_role(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("moderation.settings.edit")),
):
    return await check_mute_role_setting(session=session, server_id=server_id)


@server_moderation_settings_router.post(
    "/test-mod-log",
    response_model=ServerModerationSettingsTestResultModel,
)
async def test_server_mod_log(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("moderation.settings.edit")),
):
    return await check_mod_log_setting(session=session, server_id=server_id)
