from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.server_overview_settings import (
    ServerOverviewSettingsReadModel,
    ServerOverviewSettingsUpdateModel,
)
from api.services.server_overview_settings import (
    get_or_create_server_overview_settings,
    to_server_overview_settings_read_model,
    update_server_overview_settings,
)
from src.db.database import get_session


server_overview_settings_router = APIRouter(
    prefix="/servers/{server_id}/overview-settings",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_overview_settings_router.get("", response_model=ServerOverviewSettingsReadModel)
async def get_server_overview_settings(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    settings = await get_or_create_server_overview_settings(session, server_id)
    return to_server_overview_settings_read_model(settings)


@server_overview_settings_router.put("", response_model=ServerOverviewSettingsReadModel)
async def set_server_overview_settings(
    server_id: int,
    body: ServerOverviewSettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("overview.settings.edit")),
):
    settings = await update_server_overview_settings(
        session=session,
        server_id=server_id,
        body=body,
    )
    return to_server_overview_settings_read_model(settings)
