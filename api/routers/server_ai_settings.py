from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import get_current_discord_user_id
from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.ai_settings import ServerAISettingsHealthModel, ServerAISettingsReadModel, ServerAISettingsUpdateModel
from api.services.ai_settings import (
    get_or_create_server_ai_settings,
    to_server_ai_settings_read_model,
    update_server_ai_settings,
)
from api.services.ai_settings_health import build_ai_settings_health
from api.services.rbac_service import assert_user_has_permission
from src.db.database import get_session

server_ai_settings_router = APIRouter(
    prefix="/servers/{server_id}/ai-settings",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_ai_settings_router.get("", response_model=ServerAISettingsReadModel)
async def get_server_ai_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
):
    settings = await get_or_create_server_ai_settings(session, server_id)
    payload = to_server_ai_settings_read_model(settings)
    try:
        await assert_user_has_permission(
            session=session,
            server_id=server_id,
            user_id=current_user_id,
            permission_key="ai.settings.edit",
            access_token=access_token,
        )
        payload.permissions.can_edit = True
    except HTTPException as error:
        if error.status_code != 403:
            raise
        payload.permissions.can_edit = False
    return payload


@server_ai_settings_router.get("/health", response_model=ServerAISettingsHealthModel)
async def get_server_ai_settings_health(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    return await build_ai_settings_health(session=session, server_id=server_id)


@server_ai_settings_router.put("", response_model=ServerAISettingsReadModel)
async def set_server_ai_settings(
    server_id: int,
    body: ServerAISettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("ai.settings.edit")),
):
    settings = await update_server_ai_settings(session=session, server_id=server_id, body=body)
    payload = to_server_ai_settings_read_model(settings)
    payload.permissions.can_edit = True
    return payload
