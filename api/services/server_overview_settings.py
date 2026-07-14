from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_overview_settings import (
    ServerOverviewSettingsReadModel,
    ServerOverviewSettingsUpdateModel,
)
from api.services.moderation_core import naive_utcnow
from src.db.models import Server, ServerOverviewSettings


async def get_or_create_server_overview_settings(
    session: AsyncSession,
    server_id: int,
) -> ServerOverviewSettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerOverviewSettings, server_id)
    if settings:
        return settings

    settings = ServerOverviewSettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


def to_server_overview_settings_read_model(
    settings: ServerOverviewSettings,
) -> ServerOverviewSettingsReadModel:
    return ServerOverviewSettingsReadModel(
        server_id=str(settings.server_id),
        role_ids=settings.role_ids or [],
        updated_at=settings.updated_at,
    )


async def update_server_overview_settings(
    *,
    session: AsyncSession,
    server_id: int,
    body: ServerOverviewSettingsUpdateModel,
) -> ServerOverviewSettings:
    settings = await get_or_create_server_overview_settings(session, server_id)
    settings.role_ids = body.role_ids
    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings
