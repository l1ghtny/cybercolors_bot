from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_localization import (
    ServerLocalizationSettingsReadModel,
    ServerLocalizationSettingsUpdateModel,
)
from src.db.models import ServerLocalizationSettings
from src.modules.localization.catalog import SUPPORTED_LOCALES
from src.modules.localization.service import (
    get_or_create_server_localization_settings,
    normalize_locale_code,
)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def to_server_localization_read_model(
    server_id: int,
    settings: ServerLocalizationSettings,
) -> ServerLocalizationSettingsReadModel:
    return ServerLocalizationSettingsReadModel(
        server_id=str(server_id),
        locale_code=normalize_locale_code(settings.locale_code),
        supported_locales=list(SUPPORTED_LOCALES),
        updated_at=settings.updated_at,
    )


async def get_server_localization_settings(
    session: AsyncSession,
    server_id: int,
) -> ServerLocalizationSettings:
    return await get_or_create_server_localization_settings(session=session, server_id=server_id)


async def update_server_localization_settings(
    session: AsyncSession,
    server_id: int,
    body: ServerLocalizationSettingsUpdateModel,
) -> ServerLocalizationSettings:
    locale_code = normalize_locale_code(body.locale_code)
    if locale_code not in SUPPORTED_LOCALES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported locale_code. Supported values: {', '.join(SUPPORTED_LOCALES)}",
        )
    settings = await get_or_create_server_localization_settings(session=session, server_id=server_id)
    settings.locale_code = locale_code
    settings.updated_at = _utcnow_naive()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
