from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.user_profiles import (
    MemberHistoryEventModel,
    MemberNoteCreateModel,
    MemberNoteReadModel,
)
from api.models.moderation_cases import ModerationActorModel
from api.services.moderation_actions_service import list_action_summaries
from api.services.moderation_core import build_actor, build_optional_actor, utc_now
from src.db.models import (
    GlobalUser,
    MemberNote,
    ModerationCase,
    ModerationCaseNote,
    ModerationCaseUser,
    MonitoredUser,
    MonitoredUserComment,
    MonitoredUserStatusEvent,
    Server,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _cases_for_user_clause(user_id: int):
    return or_(
        ModerationCase.target_user_id == user_id,
        ModerationCase.id.in_(
            select(ModerationCaseUser.case_id).where(ModerationCaseUser.user_id == user_id)
        ),
    )


async def _member_note_to_read(
    session: AsyncSession,
    item: MemberNote,
    actor_cache: dict[int, ModerationActorModel | None] | None = None,
) -> MemberNoteReadModel:
    async def actor(user_id: int | None) -> ModerationActorModel | None:
        if user_id is None:
            return None
        if actor_cache is None:
            return await build_optional_actor(session, item.server_id, user_id)
        if user_id not in actor_cache:
            actor_cache[user_id] = await build_optional_actor(session, item.server_id, user_id)
        return actor_cache[user_id]

    return MemberNoteReadModel(
        id=str(item.id),
        server_id=str(item.server_id),
        user_id=str(item.user_id),
        note=item.note,
        created_at=item.created_at,
        author=await actor(item.author_user_id),
        deleted_at=item.deleted_at,
        deleted_by=await actor(item.deleted_by_user_id),
        deletion_reason=item.deletion_reason,
    )


async def list_member_notes(
    *,
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
    include_deleted: bool = False,
) -> list[MemberNoteReadModel]:
    statement = select(MemberNote).where(
        MemberNote.server_id == server_id,
        MemberNote.user_id == user_id,
    )
    if not include_deleted:
        statement = statement.where(MemberNote.deleted_at.is_(None))
    rows = (
        await session.exec(
            statement.order_by(MemberNote.created_at.desc(), MemberNote.id.desc()).limit(limit)
        )
    ).all()
    actor_cache: dict[int, ModerationActorModel | None] = {}
    return [await _member_note_to_read(session, item, actor_cache) for item in rows]


async def create_member_note(
    *,
    session: AsyncSession,
    server_id: int,
    user_id: int,
    author_user_id: int,
    body: MemberNoteCreateModel,
) -> MemberNoteReadModel:
    if await session.get(Server, server_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if await session.get(GlobalUser, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await build_actor(session, server_id, author_user_id, require_membership=True)

    item = MemberNote(
        server_id=server_id,
        user_id=user_id,
        author_user_id=author_user_id,
        note=body.note,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return await _member_note_to_read(session, item)


async def delete_member_note(
    *,
    session: AsyncSession,
    server_id: int,
    user_id: int,
    note_id: UUID,
    deleted_by_user_id: int,
    reason: str,
) -> MemberNoteReadModel:
    item = await session.get(MemberNote, note_id)
    if item is None or item.server_id != server_id or item.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member note not found")
    if item.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member note is already removed")
    await build_actor(session, server_id, deleted_by_user_id, require_membership=True)

    item.note = None
    item.deleted_at = utc_now()
    item.deleted_by_user_id = deleted_by_user_id
    item.deletion_reason = reason
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return await _member_note_to_read(session, item)


async def list_member_history(
    *,
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
    before: datetime | None = None,
) -> list[MemberHistoryEventModel]:
    if await session.get(Server, server_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    if await session.get(GlobalUser, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    cutoff = _as_utc(before) if before is not None else None
    events: list[MemberHistoryEventModel] = []
    actor_cache: dict[int, ModerationActorModel | None] = {}

    async def actor(user_id: int | None) -> ModerationActorModel | None:
        if user_id is None:
            return None
        if user_id not in actor_cache:
            actor_cache[user_id] = await build_optional_actor(session, server_id, user_id)
        return actor_cache[user_id]

    note_statement = select(MemberNote).where(
        MemberNote.server_id == server_id,
        MemberNote.user_id == user_id,
    )
    if cutoff is not None:
        note_statement = note_statement.where(
            func.coalesce(MemberNote.deleted_at, MemberNote.created_at) < cutoff
        )
    note_rows = (
        await session.exec(
            note_statement.order_by(
                func.coalesce(MemberNote.deleted_at, MemberNote.created_at).desc()
            ).limit(limit)
        )
    ).all()
    for item in note_rows:
        if item.deleted_at is not None:
            occurred_at = _as_utc(item.deleted_at)
            if cutoff is not None and occurred_at >= cutoff:
                continue
            events.append(
                MemberHistoryEventModel(
                    id=f"member_note_removed:{item.id}",
                    event_type="member_note_removed",
                    occurred_at=occurred_at,
                    actor=await actor(item.deleted_by_user_id),
                    reason=item.deletion_reason,
                )
            )
            continue
        occurred_at = _as_utc(item.created_at)
        if cutoff is not None and occurred_at >= cutoff:
            continue
        events.append(
            MemberHistoryEventModel(
                id=f"member_note:{item.id}",
                event_type="member_note",
                occurred_at=occurred_at,
                actor=await actor(item.author_user_id),
                note=item.note,
            )
        )

    action_rows = await list_action_summaries(
        session=session,
        server_id=server_id,
        target_user_id=user_id,
        limit=limit,
        before=cutoff,
    )
    for item in action_rows:
        occurred_at = _as_utc(item.created_at)
        if cutoff is not None and occurred_at >= cutoff:
            continue
        events.append(
            MemberHistoryEventModel(
                id=f"moderation_action:{item.id}",
                event_type="moderation_action",
                occurred_at=occurred_at,
                actor=await actor(int(item.moderator_user_id)),
                reason=item.reason,
                commentary=item.commentary,
                action_id=item.id,
                action_number=item.action_number,
                action_type=item.action_type.value if hasattr(item.action_type, "value") else str(item.action_type),
                action_active=item.is_active,
                action_resolution=item.resolution_type,
                case_id=item.case_id,
                case_title=item.case_title,
                source=item.import_source or "modral",
            )
        )

    case_note_statement = (
        select(ModerationCaseNote, ModerationCase.title)
        .join(ModerationCase, ModerationCase.id == ModerationCaseNote.case_id)
        .where(
            ModerationCase.server_id == server_id,
            _cases_for_user_clause(user_id),
        )
    )
    if cutoff is not None:
        case_note_statement = case_note_statement.where(ModerationCaseNote.created_at < cutoff)
    case_note_rows = (
        await session.exec(
            case_note_statement.order_by(ModerationCaseNote.created_at.desc()).limit(limit)
        )
    ).all()
    for item, case_title in case_note_rows:
        occurred_at = _as_utc(item.created_at)
        events.append(
            MemberHistoryEventModel(
                id=f"case_note:{item.id}",
                event_type="case_note",
                occurred_at=occurred_at,
                actor=await actor(item.author_user_id),
                note=item.note,
                case_id=str(item.case_id),
                case_title=case_title,
            )
        )

    monitored_user = (
        await session.exec(
            select(MonitoredUser).where(
                MonitoredUser.server_id == server_id,
                MonitoredUser.user_id == user_id,
            )
        )
    ).first()
    if monitored_user is not None:
        comment_statement = select(MonitoredUserComment).where(
            MonitoredUserComment.monitored_user_id == monitored_user.id
        )
        if cutoff is not None:
            comment_statement = comment_statement.where(MonitoredUserComment.created_at < cutoff)
        comment_rows = (
            await session.exec(
                comment_statement.order_by(MonitoredUserComment.created_at.desc()).limit(limit)
            )
        ).all()
        for item in comment_rows:
            events.append(
                MemberHistoryEventModel(
                    id=f"monitoring_comment:{item.id}",
                    event_type="monitoring_comment",
                    occurred_at=_as_utc(item.created_at),
                    actor=await actor(item.author_user_id),
                    note=item.comment,
                    source=monitored_user.source,
                )
            )

        status_statement = select(MonitoredUserStatusEvent).where(
            MonitoredUserStatusEvent.monitored_user_id == monitored_user.id
        )
        if cutoff is not None:
            status_statement = status_statement.where(
                MonitoredUserStatusEvent.changed_at < cutoff
            )
        status_rows = (
            await session.exec(
                status_statement.order_by(MonitoredUserStatusEvent.changed_at.desc()).limit(limit)
            )
        ).all()
        for item in status_rows:
            occurred_at = _as_utc(item.changed_at)
            if cutoff is not None and occurred_at >= cutoff:
                continue
            events.append(
                MemberHistoryEventModel(
                    id=f"monitoring_status:{item.id}",
                    event_type="monitoring_enabled" if item.to_is_active else "monitoring_disabled",
                    occurred_at=occurred_at,
                    actor=await actor(item.changed_by_user_id),
                    reason=item.reason,
                    monitoring_active=item.to_is_active,
                    source=monitored_user.source,
                )
            )

    case_statement = select(ModerationCase).where(
        ModerationCase.server_id == server_id,
        _cases_for_user_clause(user_id),
    )
    if cutoff is not None:
        case_statement = case_statement.where(
            or_(
                ModerationCase.created_at < cutoff,
                ModerationCase.closed_at < cutoff,
            )
        )
    case_rows = (
        await session.exec(
            case_statement.order_by(
                func.coalesce(ModerationCase.closed_at, ModerationCase.created_at).desc()
            ).limit(limit)
        )
    ).all()
    for item in case_rows:
        created_at = _as_utc(item.created_at)
        if cutoff is None or created_at < cutoff:
            events.append(
                MemberHistoryEventModel(
                    id=f"case_opened:{item.id}",
                    event_type="case_opened",
                    occurred_at=created_at,
                    actor=await actor(item.opened_by_user_id),
                    reason=item.summary,
                    case_id=str(item.id),
                    case_title=item.title,
                    case_status=item.status.value if hasattr(item.status, "value") else str(item.status),
                )
            )
        if item.closed_at is not None:
            closed_at = _as_utc(item.closed_at)
            if cutoff is None or closed_at < cutoff:
                case_status = item.status.value if hasattr(item.status, "value") else str(item.status)
                events.append(
                    MemberHistoryEventModel(
                        id=f"case_closed:{item.id}",
                        event_type="case_archived" if case_status == "archived" else "case_closed",
                        occurred_at=closed_at,
                        actor=await actor(item.closed_by_user_id),
                        case_id=str(item.id),
                        case_title=item.title,
                        case_status=case_status,
                    )
                )

    events.sort(key=lambda item: (_as_utc(item.occurred_at), item.id), reverse=True)
    return events[:limit]
