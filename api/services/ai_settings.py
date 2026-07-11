from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.ai_settings import ServerAISettingsReadModel, ServerAISettingsUpdateModel
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, fetch_channel
from api.services.moderation_core import naive_utcnow
from src.db.models import Server, ServerAISettings


def _validate_selected_mode(mode: str, ids: list[str], field_name: str) -> None:
    if mode == "selected" and not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} cannot be empty when mode is selected",
        )


async def _validate_text_channel(server_id: int, channel_id: int, field_name: str) -> None:
    channel = await fetch_channel(server_id=server_id, channel_id=channel_id)
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} is not a channel in this server",
        )
    if channel.get("type") not in TEXT_CHANNEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be a text or announcement channel",
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
        answer_enabled=settings.answer_enabled,
        answer_channel_mode=settings.answer_channel_mode,
        answer_allowed_channel_ids=list(settings.answer_allowed_channel_ids or []),
        answer_allowed_role_ids=list(settings.answer_allowed_role_ids or []),
        moderation_enabled=settings.moderation_enabled,
        moderation_channel_mode=settings.moderation_channel_mode,
        moderation_included_channel_ids=list(settings.moderation_included_channel_ids or []),
        moderation_excluded_channel_ids=list(settings.moderation_excluded_channel_ids or []),
        moderation_monitor_attachments=settings.moderation_monitor_attachments,
        moderation_monitor_bots=settings.moderation_monitor_bots,
        moderation_strictness=settings.moderation_strictness,
        moderation_action_mode=settings.moderation_action_mode,
        moderation_review_channel_id=(
            str(settings.moderation_review_channel_id)
            if settings.moderation_review_channel_id is not None
            else None
        ),
        log_ai_decisions=settings.log_ai_decisions,
        moderation_kill_switch_enabled=settings.moderation_kill_switch_enabled,
        moderation_daily_token_limit=settings.moderation_daily_token_limit,
        moderation_provider_timeout_seconds=settings.moderation_provider_timeout_seconds,
        answer_persona=settings.answer_persona,
        server_brief=settings.server_brief,
        updated_at=settings.updated_at,
    )


async def update_server_ai_settings(
    session: AsyncSession,
    server_id: int,
    body: ServerAISettingsUpdateModel,
    server_name: str | None = None,
) -> ServerAISettings:
    settings = await get_or_create_server_ai_settings(session, server_id, server_name=server_name)

    if body.answer_enabled is not None:
        settings.answer_enabled = body.answer_enabled
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
    if body.moderation_excluded_channel_ids is not None:
        settings.moderation_excluded_channel_ids = body.moderation_excluded_channel_ids
    if body.moderation_monitor_attachments is not None:
        settings.moderation_monitor_attachments = body.moderation_monitor_attachments
    if body.moderation_monitor_bots is not None:
        settings.moderation_monitor_bots = body.moderation_monitor_bots
    if body.moderation_strictness is not None:
        settings.moderation_strictness = body.moderation_strictness
    if body.moderation_action_mode is not None:
        settings.moderation_action_mode = body.moderation_action_mode
    if "moderation_review_channel_id" in body.model_fields_set:
        if body.moderation_review_channel_id:
            review_channel_id = int(body.moderation_review_channel_id)
            await _validate_text_channel(server_id, review_channel_id, "moderation_review_channel_id")
            settings.moderation_review_channel_id = review_channel_id
        else:
            settings.moderation_review_channel_id = None
    if body.log_ai_decisions is not None:
        settings.log_ai_decisions = body.log_ai_decisions
    if body.moderation_kill_switch_enabled is not None:
        settings.moderation_kill_switch_enabled = body.moderation_kill_switch_enabled
    if "moderation_daily_token_limit" in body.model_fields_set:
        settings.moderation_daily_token_limit = body.moderation_daily_token_limit
    if body.moderation_provider_timeout_seconds is not None:
        settings.moderation_provider_timeout_seconds = body.moderation_provider_timeout_seconds
    if "answer_persona" in body.model_fields_set:
        settings.answer_persona = body.answer_persona
    if "server_brief" in body.model_fields_set:
        settings.server_brief = body.server_brief

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
    if settings.moderation_channel_mode == "exclude_selected" and not list(settings.moderation_excluded_channel_ids or []):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="moderation_excluded_channel_ids cannot be empty when mode is exclude_selected",
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
    if not settings.answer_enabled:
        return False
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
    if settings.moderation_review_channel_id == channel_id:
        return False
    if settings.moderation_channel_mode == "none":
        return False
    if settings.moderation_channel_mode == "selected":
        return str(channel_id) in set(settings.moderation_included_channel_ids or [])
    if settings.moderation_channel_mode == "exclude_selected":
        return str(channel_id) not in set(settings.moderation_excluded_channel_ids or [])
    return True
