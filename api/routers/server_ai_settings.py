from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_admin_or_owner, require_server_dashboard_access
from api.models.ai_settings import ServerAISettingsReadModel, ServerAISettingsUpdateModel
from api.services.ai_settings import (
    get_or_create_server_ai_settings,
    to_server_ai_settings_read_model,
    update_server_ai_settings,
)
from src.db.database import get_session

server_ai_settings_router = APIRouter(
    prefix="/servers/{server_id}/ai-settings",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_ai_settings_router.get("", response_model=ServerAISettingsReadModel)
async def get_server_ai_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    settings = await get_or_create_server_ai_settings(session, server_id)
    return to_server_ai_settings_read_model(settings)


@server_ai_settings_router.put("", response_model=ServerAISettingsReadModel)
async def set_server_ai_settings(
    server_id: int,
    body: ServerAISettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_server_admin_or_owner),
):
    settings = await update_server_ai_settings(session=session, server_id=server_id, body=body)
    return to_server_ai_settings_read_model(settings)
