from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.monitoring import (
    MonitoredUserCommentReadModel,
    MonitoredUserReadModel,
    MonitoredUserStatusEventReadModel,
)
from api.services.moderation_core import build_actor, naive_utcnow
from src.db.models import MonitoredUser, MonitoredUserComment, MonitoredUserStatusEvent


async def _to_monitored_user_read(session: AsyncSession, item: MonitoredUser) -> MonitoredUserReadModel:
    return MonitoredUserReadModel(
        id=str(item.id),
        server_id=str(item.server_id),
        reason=item.reason,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
        user=await build_actor(session, item.server_id, item.user_id),
        added_by=await build_actor(session, item.server_id, item.added_by_user_id),
    )


def _to_monitored_user_comment_read(
    item: MonitoredUserComment,
    author,
) -> MonitoredUserCommentReadModel:
    return MonitoredUserCommentReadModel(
        id=str(item.id),
        monitored_user_id=str(item.monitored_user_id),
        comment=item.comment,
        created_at=item.created_at,
        author=author,
    )


def _to_monitored_user_status_event_read(
    item: MonitoredUserStatusEvent,
    changed_by,
) -> MonitoredUserStatusEventReadModel:
    return MonitoredUserStatusEventReadModel(
        id=str(item.id),
        monitored_user_id=str(item.monitored_user_id),
        from_is_active=item.from_is_active,
        to_is_active=item.to_is_active,
        changed_at=item.changed_at,
        changed_by=changed_by,
    )


async def _get_monitored_user_or_none(
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> MonitoredUser | None:
    return (
        await session.exec(
            select(MonitoredUser).where(
                MonitoredUser.server_id == server_id,
                MonitoredUser.user_id == user_id,
            )
        )
    ).first()


def _append_status_event(
    session: AsyncSession,
    monitored_user_id,
    changed_by_user_id: int,
    from_is_active: bool | None,
    to_is_active: bool,
):
    session.add(
        MonitoredUserStatusEvent(
            monitored_user_id=monitored_user_id,
            changed_by_user_id=changed_by_user_id,
            from_is_active=from_is_active,
            to_is_active=to_is_active,
        )
    )


async def list_monitored_users(
    session: AsyncSession,
    server_id: int,
    active_only: bool = True,
) -> list[MonitoredUserReadModel]:
    statement = select(MonitoredUser).where(MonitoredUser.server_id == server_id)
    if active_only:
        statement = statement.where(MonitoredUser.is_active.is_(True))
    statement = statement.order_by(MonitoredUser.updated_at.desc())
    rows = (await session.exec(statement)).all()
    return [await _to_monitored_user_read(session, row) for row in rows]


async def upsert_monitored_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    reason: str | None,
    added_by_user_id: int,
) -> MonitoredUserReadModel:
    await build_actor(session, server_id, user_id)
    await build_actor(session, server_id, added_by_user_id, require_membership=True)

    existing = (
        await session.exec(
            select(MonitoredUser).where(
                MonitoredUser.server_id == server_id,
                MonitoredUser.user_id == user_id,
            )
        )
    ).first()

    if existing:
        previous_active = existing.is_active
        existing.is_active = True
        if reason is not None:
            existing.reason = reason
        existing.added_by_user_id = added_by_user_id
        existing.updated_at = naive_utcnow()
        session.add(existing)
        if previous_active is not True:
            _append_status_event(
                session=session,
                monitored_user_id=existing.id,
                changed_by_user_id=added_by_user_id,
                from_is_active=previous_active,
                to_is_active=True,
            )
        await session.flush()
        await session.refresh(existing)
        return await _to_monitored_user_read(session, existing)

    item = MonitoredUser(
        server_id=server_id,
        user_id=user_id,
        added_by_user_id=added_by_user_id,
        reason=reason,
        is_active=True,
    )
    session.add(item)
    await session.flush()
    _append_status_event(
        session=session,
        monitored_user_id=item.id,
        changed_by_user_id=added_by_user_id,
        from_is_active=None,
        to_is_active=True,
    )
    await session.flush()
    await session.refresh(item)
    return await _to_monitored_user_read(session, item)


async def update_monitored_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    reason: str | None,
    is_active: bool | None,
    updated_by_user_id: int,
) -> MonitoredUserReadModel:
    item = (
        await session.exec(
            select(MonitoredUser).where(
                MonitoredUser.server_id == server_id,
                MonitoredUser.user_id == user_id,
            )
        )
    ).first()
    if not item:
        raise LookupError("Monitored user not found")

    await build_actor(session, server_id, updated_by_user_id, require_membership=True)
    previous_active = item.is_active
    if reason is not None:
        item.reason = reason
    if is_active is not None:
        item.is_active = is_active
    if is_active is not None and is_active != previous_active:
        _append_status_event(
            session=session,
            monitored_user_id=item.id,
            changed_by_user_id=updated_by_user_id,
            from_is_active=previous_active,
            to_is_active=is_active,
        )
    item.updated_at = naive_utcnow()
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return await _to_monitored_user_read(session, item)


async def list_monitored_user_comments(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
) -> list[MonitoredUserCommentReadModel]:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")

    rows = (
        await session.exec(
            select(MonitoredUserComment)
            .where(MonitoredUserComment.monitored_user_id == monitored_user.id)
            .order_by(MonitoredUserComment.created_at.desc())
            .limit(limit)
        )
    ).all()

    payload: list[MonitoredUserCommentReadModel] = []
    for row in rows:
        author = await build_actor(session, server_id, row.author_user_id)
        payload.append(_to_monitored_user_comment_read(row, author))
    return payload


async def add_monitored_user_comment(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    comment: str,
    author_user_id: int,
) -> MonitoredUserCommentReadModel:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")

    author = await build_actor(session, server_id, author_user_id, require_membership=True)
    row = MonitoredUserComment(
        monitored_user_id=monitored_user.id,
        author_user_id=author_user_id,
        comment=comment,
    )
    session.add(row)

    monitored_user.updated_at = naive_utcnow()
    session.add(monitored_user)

    await session.flush()
    await session.refresh(row)
    return _to_monitored_user_comment_read(row, author)


async def list_monitored_user_status_events(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
) -> list[MonitoredUserStatusEventReadModel]:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")

    rows = (
        await session.exec(
            select(MonitoredUserStatusEvent)
            .where(MonitoredUserStatusEvent.monitored_user_id == monitored_user.id)
            .order_by(MonitoredUserStatusEvent.changed_at.desc())
            .limit(limit)
        )
    ).all()

    payload: list[MonitoredUserStatusEventReadModel] = []
    for row in rows:
        changed_by = await build_actor(session, server_id, row.changed_by_user_id)
        payload.append(_to_monitored_user_status_event_read(row, changed_by))
    return payload
