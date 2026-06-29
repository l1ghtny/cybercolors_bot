from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.ai_settings import ServerAISettingsReadModel, ServerAISettingsUpdateModel
from api.services.moderation_core import naive_utcnow
from src.db.models import Server, ServerAISettings


def _validate_selected_mode(mode: str, ids: list[str], field_name: str) -> None:
    if mode == "selected" and not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} cannot be empty when mode is selected",
        )


async def get_or_create_server_ai_settings(
    session: AsyncSession,
    server_id: int,
    server_name: str | None = None,
) -> ServerAISettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=server_name or str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerAISettings, server_id)
    if settings:
        return settings

    settings = ServerAISettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


def to_server_ai_settings_read_model(settings: ServerAISettings) -> ServerAISettingsReadModel:
    return ServerAISettingsReadModel(
        server_id=str(settings.server_id),
        answer_channel_mode=settings.answer_channel_mode,
        answer_allowed_channel_ids=list(settings.answer_allowed_channel_ids or []),
        answer_allowed_role_ids=list(settings.answer_allowed_role_ids or []),
        moderation_enabled=settings.moderation_enabled,
        moderation_channel_mode=settings.moderation_channel_mode,
        moderation_included_channel_ids=list(settings.moderation_included_channel_ids or []),
        moderation_monitor_attachments=settings.moderation_monitor_attachments,
        moderation_monitor_bots=settings.moderation_monitor_bots,
        moderation_strictness=settings.moderation_strictness,
        moderation_action_mode=settings.moderation_action_mode,
        log_ai_decisions=settings.log_ai_decisions,
        updated_at=settings.updated_at,
    )


async def update_server_ai_settings(
    session: AsyncSession,
    server_id: int,
    body: ServerAISettingsUpdateModel,
    server_name: str | None = None,
) -> ServerAISettings:
    settings = await get_or_create_server_ai_settings(session, server_id, server_name=server_name)

    if body.answer_channel_mode is not None:
        settings.answer_channel_mode = body.answer_channel_mode
    if body.answer_allowed_channel_ids is not None:
        settings.answer_allowed_channel_ids = body.answer_allowed_channel_ids
    if body.answer_allowed_role_ids is not None:
        settings.answer_allowed_role_ids = body.answer_allowed_role_ids
    if body.moderation_enabled is not None:
        settings.moderation_enabled = body.moderation_enabled
    if body.moderation_channel_mode is not None:
        settings.moderation_channel_mode = body.moderation_channel_mode
    if body.moderation_included_channel_ids is not None:
        settings.moderation_included_channel_ids = body.moderation_included_channel_ids
    if body.moderation_monitor_attachments is not None:
        settings.moderation_monitor_attachments = body.moderation_monitor_attachments
    if body.moderation_monitor_bots is not None:
        settings.moderation_monitor_bots = body.moderation_monitor_bots
    if body.moderation_strictness is not None:
        settings.moderation_strictness = body.moderation_strictness
    if body.moderation_action_mode is not None:
        settings.moderation_action_mode = body.moderation_action_mode
    if body.log_ai_decisions is not None:
        settings.log_ai_decisions = body.log_ai_decisions

    _validate_selected_mode(
        settings.answer_channel_mode,
        list(settings.answer_allowed_channel_ids or []),
        "answer_allowed_channel_ids",
    )
    _validate_selected_mode(
        settings.moderation_channel_mode,
        list(settings.moderation_included_channel_ids or []),
        "moderation_included_channel_ids",
    )

    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


def can_invoke_answer_flow(
    settings: ServerAISettings,
    *,
    channel_id: int,
    role_ids: list[int] | list[str],
) -> bool:
    if settings.answer_channel_mode == "none":
        return False
    if settings.answer_channel_mode == "selected" and str(channel_id) not in set(settings.answer_allowed_channel_ids or []):
        return False
    allowed_roles = set(settings.answer_allowed_role_ids or [])
    if allowed_roles and not allowed_roles.intersection({str(role_id) for role_id in role_ids}):
        return False
    return True


def should_moderate_message_channel(settings: ServerAISettings, *, channel_id: int) -> bool:
    if not settings.moderation_enabled:
        return False
    if settings.moderation_channel_mode == "none":
        return False
    if settings.moderation_channel_mode == "selected":
        return str(channel_id) in set(settings.moderation_included_channel_ids or [])
    return True
