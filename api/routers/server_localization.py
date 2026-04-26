from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_current_discord_user_id
from api.models.server_localization import (
    ServerLocalizationSettingsReadModel,
    ServerLocalizationSettingsUpdateModel,
)
from api.services.dashboard_access_service import assert_dashboard_access, assert_server_admin_or_owner
from api.services.server_localization import (
    get_server_localization_settings,
    to_server_localization_read_model,
    update_server_localization_settings,
)
from src.db.database import get_session

server_localization_router = APIRouter(prefix="/servers/{server_id}/localization")


@server_localization_router.get("", response_model=ServerLocalizationSettingsReadModel)
async def get_server_localization(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    authorization: Annotated[str | None, Header()] = None,
):
    await assert_dashboard_access(
        session=session,
        server_id=server_id,
        caller_user_id=current_user_id,
        authorization=authorization,
    )
    settings = await get_server_localization_settings(session=session, server_id=server_id)
    return await to_server_localization_read_model(server_id, settings)


@server_localization_router.put("", response_model=ServerLocalizationSettingsReadModel)
async def set_server_localization(
    server_id: int,
    body: ServerLocalizationSettingsUpdateModel,
    session: AsyncSession = Depends(get_session),
    authorization: Annotated[str | None, Header()] = None,
):
    await assert_server_admin_or_owner(server_id=server_id, authorization=authorization)
    settings = await update_server_localization_settings(session=session, server_id=server_id, body=body)
    return await to_server_localization_read_model(server_id, settings)
