from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_admin_or_owner, require_server_dashboard_access
from api.models.server_localization import (
    ServerLocalizationSettingsReadModel,
    ServerLocalizationSettingsUpdateModel,
)
from api.services.server_localization import (
    get_server_localization_settings,
    to_server_localization_read_model,
    update_server_localization_settings,
)
from src.db.database import get_session

server_localization_router = APIRouter(
    prefix="/servers/{server_id}/localization",
    dependencies=[Depends(require_server_dashboard_access)],
)


@server_localization_router.get("", response_model=ServerLocalizationSettingsReadModel)
async def get_server_localization(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    settings = await get_server_localization_settings(session=session, server_id=server_id)
    return await to_server_localization_read_model(server_id, settings)


@server_localization_router.put("", response_model=ServerLocalizationSettingsReadModel)
async def set_server_localization(
    server_id: int,
    body: ServerLocalizationSettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_server_admin_or_owner),
):
    settings = await update_server_localization_settings(session=session, server_id=server_id, body=body)
    return await to_server_localization_read_model(server_id, settings)
