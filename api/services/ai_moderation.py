import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import ProgrammingError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.ai_moderation import (
    AIApproveSuggestionModel,
    AIChannelRefModel,
    AIDismissSuggestionModel,
    AIModerationDecisionListModel,
    AIModerationDecisionModel,
    AIMessageSnapshotModel,
    AIResolveSuggestionResponseModel,
    AITweakSuggestionModel,
)
from api.models.moderation_actions import ModerationActionCreate
from api.services.discord_guilds import edit_channel_message, fetch_channel_message
from api.services.monitoring_service import upsert_monitored_user
from api.services.moderation_actions_service import create_action
from api.services.moderation_core import build_optional_actor, naive_utcnow, to_moderation_history
from src.modules.localization.service import normalize_locale_code, tr
from src.db.models import AIModerationDecision, ActionType, GlobalUser, Server, ServerLocalizationSettings, ServerModerationSettings, TempVoiceLog, User

PENDING_SUGGESTION_STATUSES = {"pending_review", "action_requested", "case_created", "case_linked"}
ACTIONABLE_SUGGESTIONS = {
    "warn": ActionType.WARN,
    "mute": ActionType.MUTE,
    "kick": ActionType.KICK,
    "ban": ActionType.BAN,
}


def _encode_cursor(decision: AIModerationDecision) -> str:
    payload = {"created_at": decision.created_at.isoformat(), "id": str(decision.id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid cursor")


def _normalize_status_filter(status_filter: str | None) -> str | None:
    if status_filter is None:
        return "pending_review"
    if status_filter == "pending":
        return "pending_review"
    if status_filter == "all":
        return None
    return status_filter


def _channel_ref(decision: AIModerationDecision) -> AIChannelRefModel:
    return AIChannelRefModel(
        id=str(decision.channel_id),
        mention=f"<#{decision.channel_id}>",
        name=None,
    )


async def _message_snapshot(session: AsyncSession, decision: AIModerationDecision) -> AIMessageSnapshotModel:
    archive_channel_id = decision.archive_channel_id
    archive_message_id = decision.archive_message_id
    channel_deleted = bool(archive_channel_id and archive_message_id)
    if not channel_deleted:
        temp_log = (
            await session.exec(
                select(TempVoiceLog)
                .where(
                    TempVoiceLog.server_id == decision.server_id,
                    TempVoiceLog.channel_id == decision.channel_id,
                    TempVoiceLog.deleted_at.is_not(None),
                )
                .order_by(TempVoiceLog.deleted_at.desc())
            )
        ).first()
        if temp_log is not None:
            archive_channel_id = temp_log.archive_channel_id
            archive_message_id = temp_log.archive_message_id
            channel_deleted = True
    archive_jump_url = (
        f"https://discord.com/channels/{decision.server_id}/{archive_channel_id}/{archive_message_id}"
        if archive_channel_id and archive_message_id
        else None
    )
    return AIMessageSnapshotModel(
        id=str(decision.message_id),
        content=decision.message_content,
        attachments=list(decision.attachments_json or []),
        jump_url=f"https://discord.com/channels/{decision.server_id}/{decision.channel_id}/{decision.message_id}",
        channel_deleted=channel_deleted,
        archive_channel_id=str(archive_channel_id) if archive_channel_id else None,
        archive_message_id=str(archive_message_id) if archive_message_id else None,
        archive_jump_url=archive_jump_url,
    )


async def to_ai_decision_model(session: AsyncSession, decision: AIModerationDecision) -> AIModerationDecisionModel:
    author = await build_optional_actor(session, decision.server_id, decision.author_user_id)
    reviewed_by = await build_optional_actor(session, decision.server_id, decision.reviewed_by_user_id)
    return AIModerationDecisionModel(
        id=str(decision.id),
        server_id=str(decision.server_id),
        message=await _message_snapshot(session, decision),
        channel=_channel_ref(decision),
        author=author,
        ai_reason=decision.reason,
        ai_categories=list(decision.categories or []),
        confidence=None,
        severity=decision.severity,
        suggested_action=decision.suggested_action,
        selected_action=decision.selected_action,
        action_reason=decision.action_reason,
        action_override=decision.action_override,
        rule_ids=list(decision.rule_ids or []),
        provider=decision.provider,
        model=decision.model,
        total_tokens=decision.total_tokens,
        strictness=decision.strictness,
        status=decision.status,
        flagged=decision.flagged,
        parse_error=decision.parse_error,
        review_channel_id=str(decision.review_channel_id) if decision.review_channel_id else None,
        review_message_id=str(decision.review_message_id) if decision.review_message_id else None,
        linked_case_id=str(decision.linked_case_id) if decision.linked_case_id else None,
        linked_action_id=str(decision.linked_action_id) if decision.linked_action_id else None,
        reviewed_by=reviewed_by,
        reviewed_at=decision.reviewed_at,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


async def _pending_count(session: AsyncSession, server_id: int) -> int:
    try:
        value = (
            await session.exec(
                select(func.count(AIModerationDecision.id)).where(
                    AIModerationDecision.server_id == server_id,
                    AIModerationDecision.flagged.is_(True),
                    AIModerationDecision.status.in_(PENDING_SUGGESTION_STATUSES),
                )
            )
        ).one()
    except ProgrammingError as error:
        if "ai_moderation_decisions" in str(error) and "does not exist" in str(error):
            await session.rollback()
            return 0
        raise
    return int(value or 0)


async def count_pending_ai_suggestions(session: AsyncSession, server_id: int) -> int:
    return await _pending_count(session=session, server_id=server_id)


async def get_ai_suggestion_stream_state(session: AsyncSession, server_id: int) -> dict[str, str | int | None]:
    latest = (
        await session.exec(
            select(AIModerationDecision)
            .where(
                AIModerationDecision.server_id == server_id,
                AIModerationDecision.flagged.is_(True),
                AIModerationDecision.status.in_(PENDING_SUGGESTION_STATUSES),
            )
            .order_by(AIModerationDecision.created_at.desc(), AIModerationDecision.id.desc())
            .limit(1)
        )
    ).first()
    return {
        "server_id": str(server_id),
        "unread_count": await _pending_count(session, server_id),
        "latest_suggestion_id": str(latest.id) if latest else None,
        "latest_created_at": latest.created_at.isoformat() if latest else None,
    }


def _base_decision_query(server_id: int):
    return select(AIModerationDecision).where(AIModerationDecision.server_id == server_id)


def _apply_common_filters(
    statement,
    *,
    status_filter: str | None,
    flagged: bool | None,
    author_user_id: int | None,
    channel_id: int | None,
    suggested_action: str | None,
    selected_action: str | None,
    since: datetime | None,
    until: datetime | None,
):
    normalized_status = _normalize_status_filter(status_filter)
    if normalized_status:
        statement = statement.where(AIModerationDecision.status == normalized_status)
    if flagged is not None:
        statement = statement.where(AIModerationDecision.flagged.is_(flagged))
    if author_user_id is not None:
        statement = statement.where(AIModerationDecision.author_user_id == author_user_id)
    if channel_id is not None:
        statement = statement.where(AIModerationDecision.channel_id == channel_id)
    if suggested_action:
        statement = statement.where(AIModerationDecision.suggested_action == suggested_action)
    if selected_action:
        statement = statement.where(AIModerationDecision.selected_action == selected_action)
    if since is not None:
        statement = statement.where(AIModerationDecision.created_at >= since)
    if until is not None:
        statement = statement.where(AIModerationDecision.created_at <= until)
    return statement


def _apply_cursor(statement, cursor: str | None):
    decoded = _decode_cursor(cursor)
    if decoded is None:
        return statement
    created_at, decision_id = decoded
    return statement.where(
        or_(
            AIModerationDecision.created_at < created_at,
            (AIModerationDecision.created_at == created_at) & (AIModerationDecision.id < decision_id),
        )
    )


async def list_ai_decisions(
    *,
    session: AsyncSession,
    server_id: int,
    status_filter: str | None = None,
    flagged: bool | None = None,
    author_user_id: int | None = None,
    channel_id: int | None = None,
    suggested_action: str | None = None,
    selected_action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AIModerationDecisionListModel:
    scoped_limit = max(1, min(limit, 200))
    statement = _base_decision_query(server_id)
    statement = _apply_common_filters(
        statement,
        status_filter=status_filter,
        flagged=flagged,
        author_user_id=author_user_id,
        channel_id=channel_id,
        suggested_action=suggested_action,
        selected_action=selected_action,
        since=since,
        until=until,
    )
    statement = _apply_cursor(statement, cursor)
    statement = statement.order_by(AIModerationDecision.created_at.desc(), AIModerationDecision.id.desc()).limit(scoped_limit + 1)
    rows = (await session.exec(statement)).all()
    page = rows[:scoped_limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > scoped_limit and page else None
    return AIModerationDecisionListModel(
        items=[await to_ai_decision_model(session, item) for item in page],
        next_cursor=next_cursor,
        unread_count=await _pending_count(session, server_id),
    )


async def list_ai_suggestions(
    *,
    session: AsyncSession,
    server_id: int,
    status_filter: str | None = "pending_review",
    cursor: str | None = None,
    limit: int = 50,
) -> AIModerationDecisionListModel:
    return await list_ai_decisions(
        session=session,
        server_id=server_id,
        status_filter=status_filter,
        flagged=True,
        cursor=cursor,
        limit=limit,
    )


async def get_ai_decision_or_404(session: AsyncSession, server_id: int, suggestion_id: UUID) -> AIModerationDecision:
    decision = await session.get(AIModerationDecision, suggestion_id)
    if not decision or decision.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI moderation decision not found")
    return decision


async def _target_membership(session: AsyncSession, server_id: int, user_id: int) -> tuple[GlobalUser | None, User | None]:
    global_user = await session.get(GlobalUser, user_id)
    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    return global_user, membership


def _action_type_or_422(action: str) -> ActionType:
    action_type = ACTIONABLE_SUGGESTIONS.get(action)
    if action_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Suggested action is not directly actionable. Use tweak with watch, warn, mute, kick, or ban.",
        )
    return action_type


def _duration_expires_at(duration_minutes: int | None) -> datetime | None:
    if duration_minutes is None:
        return None
    return datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)


def _valid_rule_id_strings(raw_rule_ids: list[str] | None) -> list[str]:
    parsed: list[str] = []
    seen: set[UUID] = set()
    for raw_rule_id in raw_rule_ids or []:
        try:
            parsed_id = UUID(str(raw_rule_id))
        except (TypeError, ValueError):
            continue
        if parsed_id in seen:
            continue
        seen.add(parsed_id)
        parsed.append(str(parsed_id))
    return parsed


def _ensure_decision_reviewable(decision: AIModerationDecision) -> None:
    if decision.linked_action_id or decision.status not in PENDING_SUGGESTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AI moderation suggestion has already been resolved",
        )


async def _default_duration_for_action(
    session: AsyncSession,
    server_id: int,
    action_type: ActionType,
    duration_minutes: int | None,
) -> tuple[int | None, datetime | None]:
    if action_type not in {ActionType.MUTE, ActionType.BAN}:
        return None, None

    settings = await session.get(ServerModerationSettings, server_id)
    effective_duration = duration_minutes
    if effective_duration is None and action_type == ActionType.MUTE:
        effective_duration = settings.default_mute_minutes if settings else 60
    if effective_duration is None:
        return None, None
    if settings and effective_duration > settings.max_mute_minutes and action_type == ActionType.MUTE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Mute duration exceeds the server maximum of {settings.max_mute_minutes} minutes",
        )
    return effective_duration, _duration_expires_at(effective_duration)


async def _build_action_payload_for_decision(
    *,
    session: AsyncSession,
    decision: AIModerationDecision,
    moderator_user_id: int,
    action_type: ActionType,
    reason: str | None,
    rule_ids: list[str] | None,
    duration_minutes: int | None,
) -> tuple[ModerationActionCreate, int | None]:
    server = await session.get(Server, decision.server_id)
    global_user, membership = await _target_membership(session, decision.server_id, decision.author_user_id)
    effective_duration, expires_at = await _default_duration_for_action(
        session=session,
        server_id=decision.server_id,
        action_type=action_type,
        duration_minutes=duration_minutes,
    )
    resolved_reason = reason or decision.reason or "AI moderation suggestion"
    resolved_rule_ids = rule_ids if rule_ids is not None else _valid_rule_id_strings(decision.rule_ids)
    return (
        ModerationActionCreate(
            action_type=action_type,
            moderator_user_id=moderator_user_id,
            reason=resolved_reason,
            rule_id=None,
            rule_ids=resolved_rule_ids,
            commentary=(
                f"Applied from AI decision {decision.id}. "
                f"AI suggested `{decision.suggested_action}` with severity `{decision.severity}`."
            ),
            expires_at=expires_at,
            case_id=str(decision.linked_case_id) if decision.linked_case_id else None,
            target_user_id=decision.author_user_id,
            target_user_name=(global_user.username if global_user and global_user.username else str(decision.author_user_id)),
            target_user_joined_at=naive_utcnow(),
            target_user_server_nickname=membership.server_nickname if membership else None,
            server_id=decision.server_id,
            server_name=server.server_name if server and server.server_name else str(decision.server_id),
        ),
        effective_duration,
    )


def _truncate(value: str | None, limit: int = 1000) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _resolution_color(status_value: str | None) -> int:
    return 0x57F287 if status_value == "action_applied" else 0x747F8D


def _ai_review_display(locale: str | None, kind: str, value: str | None) -> str:
    normalized = (value or "none").strip() or "none"
    return tr(locale, f"ai_review.{kind}_{normalized}")


async def _decision_locale(session: AsyncSession | None, server_id: int) -> str:
    if session is None:
        return normalize_locale_code(None)
    settings = await session.get(ServerLocalizationSettings, server_id)
    return normalize_locale_code(settings.locale_code if settings else None)


def _ai_review_resolution_embed_payload(decision: AIModerationDecision, *, action_id: str | None = None, locale: str | None = None) -> dict:
    fields = [
        {"name": tr(locale, "ai_review.field_status"), "value": f"`{_ai_review_display(locale, 'status', decision.status)}`", "inline": True},
        {"name": tr(locale, "ai_review.field_selected_action"), "value": f"`{_ai_review_display(locale, 'action', decision.selected_action)}`", "inline": True},
        {"name": tr(locale, "ai_review.field_reviewer"), "value": f"<@{decision.reviewed_by_user_id}> (`{decision.reviewed_by_user_id}`)" if decision.reviewed_by_user_id else f"`{tr(locale, 'modlog.unknown')}`", "inline": True},
    ]
    if action_id or decision.linked_action_id:
        fields.append({"name": tr(locale, "modlog.action_id_label"), "value": f"`{action_id or decision.linked_action_id}`", "inline": False})
    if decision.linked_case_id:
        fields.append({"name": tr(locale, "ai_review.field_case_id"), "value": f"`{decision.linked_case_id}`", "inline": False})
    if decision.action_reason:
        fields.append({"name": tr(locale, "modlog.reason_label"), "value": _truncate(decision.action_reason), "inline": False})
    embed = {
        "title": tr(locale, "ai_review.resolved_title"),
        "description": tr(locale, "ai_review.resolved_description"),
        "color": _resolution_color(decision.status),
        "fields": fields,
        "footer": {"text": tr(locale, "ai_review.footer_decision_id", decision_id=decision.id)},
    }
    if decision.reviewed_at:
        embed["timestamp"] = decision.reviewed_at.isoformat()
    return embed


async def _publish_ai_review_resolution(
    *,
    decision: AIModerationDecision,
    action_id: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    if not decision.review_channel_id or not decision.review_message_id:
        return
    try:
        locale = await _decision_locale(session, decision.server_id)
        original_embeds: list[dict] = []
        try:
            message = await fetch_channel_message(
                channel_id=decision.review_channel_id,
                message_id=decision.review_message_id,
            )
            embeds = message.get("embeds") if isinstance(message, dict) else None
            if isinstance(embeds, list):
                original_embeds = [item for item in embeds[:1] if isinstance(item, dict)]
        except Exception:
            original_embeds = []

        await edit_channel_message(
            channel_id=decision.review_channel_id,
            message_id=decision.review_message_id,
            embeds=[*original_embeds, _ai_review_resolution_embed_payload(decision, action_id=action_id, locale=locale)],
            components=[],
        )
    except Exception:
        # Dashboard moderation should still succeed if Discord cannot update the old review message.
        import logging

        logging.getLogger("api.ai_moderation").exception("Failed to publish AI review resolution for decision %s", decision.id)


async def _apply_decision_action(
    *,
    session: AsyncSession,
    decision: AIModerationDecision,
    moderator_user_id: int,
    action: str,
    reason: str | None,
    rule_ids: list[str] | None,
    duration_minutes: int | None,
) -> AIResolveSuggestionResponseModel:
    if action == "watch":
        _ensure_decision_reviewable(decision)
        reason = reason or decision.reason or "AI moderation watch suggestion"
        await upsert_monitored_user(
            session=session,
            server_id=decision.server_id,
            user_id=decision.author_user_id,
            reason=reason,
            added_by_user_id=moderator_user_id,
            source="ai_moderation",
        )
        decision.status = "action_applied"
        decision.reviewed_by_user_id = moderator_user_id
        decision.reviewed_at = naive_utcnow()
        decision.updated_at = naive_utcnow()
        decision.selected_action = "watch"
        decision.action_reason = reason
        decision.action_override = (decision.suggested_action or "none") != "watch"
        session.add(decision)
        await session.flush()
        await _publish_ai_review_resolution(decision=decision, action_id=None, session=session)
        return AIResolveSuggestionResponseModel(
            suggestion=await to_ai_decision_model(session, decision),
            action_id=None,
        )

    action_type = _action_type_or_422(action)
    _ensure_decision_reviewable(decision)
    payload, _effective_duration = await _build_action_payload_for_decision(
        session=session,
        decision=decision,
        moderator_user_id=moderator_user_id,
        action_type=action_type,
        reason=reason,
        rule_ids=rule_ids,
        duration_minutes=duration_minutes,
    )
    moderation_action = await create_action(
        session=session,
        action=payload,
        moderator_user_id=moderator_user_id,
        apply_discord_effects=True,
    )

    decision.status = "action_applied"
    decision.reviewed_by_user_id = moderator_user_id
    decision.reviewed_at = naive_utcnow()
    decision.updated_at = naive_utcnow()
    decision.linked_action_id = moderation_action.id
    decision.selected_action = action_type.value
    decision.action_reason = payload.reason
    decision.action_override = (decision.suggested_action or "none") != action_type.value
    session.add(decision)
    await session.flush()
    await _publish_ai_review_resolution(decision=decision, action_id=str(moderation_action.id), session=session)

    return AIResolveSuggestionResponseModel(
        suggestion=await to_ai_decision_model(session, decision),
        action_id=str(moderation_action.id),
    )


async def approve_ai_suggestion(
    *,
    session: AsyncSession,
    server_id: int,
    suggestion_id: UUID,
    moderator_user_id: int,
    body: AIApproveSuggestionModel,
) -> AIResolveSuggestionResponseModel:
    decision = await get_ai_decision_or_404(session, server_id, suggestion_id)
    action = body.override_action or decision.suggested_action
    return await _apply_decision_action(
        session=session,
        decision=decision,
        moderator_user_id=moderator_user_id,
        action=action,
        reason=body.reason,
        rule_ids=body.rule_ids,
        duration_minutes=body.duration_minutes,
    )


async def tweak_ai_suggestion(
    *,
    session: AsyncSession,
    server_id: int,
    suggestion_id: UUID,
    moderator_user_id: int,
    body: AITweakSuggestionModel,
) -> AIResolveSuggestionResponseModel:
    decision = await get_ai_decision_or_404(session, server_id, suggestion_id)
    return await _apply_decision_action(
        session=session,
        decision=decision,
        moderator_user_id=moderator_user_id,
        action=body.action,
        reason=body.reason,
        rule_ids=body.rule_ids,
        duration_minutes=body.duration_minutes,
    )


async def dismiss_ai_suggestion(
    *,
    session: AsyncSession,
    server_id: int,
    suggestion_id: UUID,
    moderator_user_id: int,
    body: AIDismissSuggestionModel,
) -> AIResolveSuggestionResponseModel:
    decision = await get_ai_decision_or_404(session, server_id, suggestion_id)
    _ensure_decision_reviewable(decision)
    decision.status = "dismissed"
    decision.reviewed_by_user_id = moderator_user_id
    decision.reviewed_at = naive_utcnow()
    decision.updated_at = naive_utcnow()
    decision.selected_action = "none"
    decision.action_reason = body.reason
    decision.action_override = (decision.suggested_action or "none") != "none"
    session.add(decision)
    await session.flush()
    await _publish_ai_review_resolution(decision=decision, action_id=None, session=session)
    return AIResolveSuggestionResponseModel(
        suggestion=await to_ai_decision_model(session, decision),
        action_id=None,
    )
