from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.monitoring import (
    MonitoredUserCountsModel,
    MonitoredUserDetailsModel,
    UserActionSummaryModel,
    UserCaseSummaryModel,
    MonitoredUserCommentReadModel,
    MonitoredUserReadModel,
    MonitoredUserStatusEventReadModel,
    MonitoredUserActivityEventReadModel,
    MonitoredUserNotificationSettingsReadModel,
    MonitoredUserNotificationSettingsUpdateModel,
    MonitoringEventDefaultsModel,
    MonitoringEventOverridesModel,
    ServerMonitoringSettingsReadModel,
    ServerMonitoringSettingsUpdateModel,
)
from api.services.moderation_core import build_actor, get_case_or_404, naive_utcnow
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, fetch_channel
from src.db.models import (
    CaseStatus,
    ModerationAction,
    ModerationCase,
    ModerationCaseUser,
    MonitoredUser,
    MonitoredUserComment,
    MonitoredUserStatusEvent,
    MonitoredUserActivityEvent,
    MonitoredUserNotificationSettings,
    Server,
    ServerModerationSettings,
    ServerMonitoringSettings,
    User,
)


async def _to_monitored_user_read(
    session: AsyncSession,
    item: MonitoredUser,
    counts: MonitoredUserCountsModel | None = None,
) -> MonitoredUserReadModel:
    return MonitoredUserReadModel(
        id=str(item.id),
        server_id=str(item.server_id),
        reason=item.reason,
        source=item.source,
        release_due_at=item.release_due_at,
        released_at=item.released_at,
        release_error=item.release_error,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
        user=await build_actor(session, item.server_id, item.user_id),
        added_by=await build_actor(session, item.server_id, item.added_by_user_id),
        counts=counts,
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


def _cases_for_user_clause(user_id: int):
    return or_(
        ModerationCase.target_user_id == user_id,
        ModerationCase.id.in_(select(ModerationCaseUser.case_id).where(ModerationCaseUser.user_id == user_id)),
    )


async def _get_monitoring_counts_for_users(
    session: AsyncSession,
    server_id: int,
    user_ids: list[int],
) -> dict[int, MonitoredUserCountsModel]:
    if not user_ids:
        return {}

    counts = {user_id: MonitoredUserCountsModel() for user_id in user_ids}
    user_id_set = set(user_ids)
    case_ids_by_user: dict[int, set] = {user_id: set() for user_id in user_ids}
    open_case_ids_by_user: dict[int, set] = {user_id: set() for user_id in user_ids}

    target_case_rows = (
        await session.exec(
            select(ModerationCase.id, ModerationCase.target_user_id, ModerationCase.status).where(
                ModerationCase.server_id == server_id,
                ModerationCase.target_user_id.in_(user_ids),
            )
        )
    ).all()
    for case_id, target_user_id, case_status in target_case_rows:
        if target_user_id not in user_id_set:
            continue
        case_ids_by_user[target_user_id].add(case_id)
        if case_status == CaseStatus.OPEN:
            open_case_ids_by_user[target_user_id].add(case_id)

    linked_case_rows = (
        await session.exec(
            select(ModerationCaseUser.user_id, ModerationCase.id, ModerationCase.status)
            .join(ModerationCase, ModerationCase.id == ModerationCaseUser.case_id)
            .where(
                ModerationCase.server_id == server_id,
                ModerationCaseUser.user_id.in_(user_ids),
            )
        )
    ).all()
    for linked_user_id, case_id, case_status in linked_case_rows:
        if linked_user_id not in user_id_set:
            continue
        case_ids_by_user[linked_user_id].add(case_id)
        if case_status == CaseStatus.OPEN:
            open_case_ids_by_user[linked_user_id].add(case_id)

    action_rows = (
        await session.exec(
            select(ModerationAction.target_user_id, func.count(ModerationAction.id))
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id.in_(user_ids),
            )
            .group_by(ModerationAction.target_user_id)
        )
    ).all()
    action_counts = {int(user_id): int(count or 0) for user_id, count in action_rows}

    for user_id in user_ids:
        counts[user_id] = MonitoredUserCountsModel(
            cases_total=len(case_ids_by_user[user_id]),
            cases_open=len(open_case_ids_by_user[user_id]),
            actions_total=action_counts.get(user_id, 0),
        )
    return counts


async def list_monitored_users(
    session: AsyncSession,
    server_id: int,
    active_only: bool = True,
    include_counts: bool = False,
    source: str | None = None,
) -> list[MonitoredUserReadModel]:
    statement = select(MonitoredUser).where(MonitoredUser.server_id == server_id)
    if active_only:
        statement = statement.where(MonitoredUser.is_active.is_(True))
    if source is not None:
        statement = statement.where(MonitoredUser.source == source)
    statement = statement.order_by(MonitoredUser.updated_at.desc())
    rows = (await session.exec(statement)).all()
    counts_map = (
        await _get_monitoring_counts_for_users(
            session=session,
            server_id=server_id,
            user_ids=[row.user_id for row in rows],
        )
        if include_counts
        else {}
    )
    return [await _to_monitored_user_read(session, row, counts=counts_map.get(row.user_id)) for row in rows]


async def upsert_monitored_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    reason: str | None,
    added_by_user_id: int,
    source: str = "manual",
    release_due_at: datetime | None = None,
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
        existing.source = source
        existing.release_due_at = release_due_at
        existing.released_at = None
        existing.release_error = None
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
        source=source,
        release_due_at=release_due_at,
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
        if item.source == "newcomer":
            if is_active:
                item.released_at = None
            else:
                item.released_at = naive_utcnow()
                item.release_due_at = None
                item.release_error = None
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


async def get_monitored_user_details(
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> MonitoredUserDetailsModel:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")

    counts = (
        await _get_monitoring_counts_for_users(
            session=session,
            server_id=server_id,
            user_ids=[user_id],
        )
    ).get(user_id, MonitoredUserCountsModel())
    base = await _to_monitored_user_read(session, monitored_user, counts=counts)

    comment_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(MonitoredUserComment)
                .where(MonitoredUserComment.monitored_user_id == monitored_user.id)
            )
        ).one()
        or 0
    )

    related_cases_rows = (
        await session.exec(
            select(ModerationCase)
            .where(
                ModerationCase.server_id == server_id,
                _cases_for_user_clause(user_id),
            )
            .order_by(ModerationCase.created_at.desc())
            .limit(20)
        )
    ).all()
    related_cases = [
        UserCaseSummaryModel(
            id=str(item.id),
            title=item.title,
            status=item.status,
            created_at=item.created_at,
        )
        for item in related_cases_rows
    ]

    recent_actions_rows = (
        await session.exec(
            select(ModerationAction)
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == user_id,
            )
            .order_by(ModerationAction.created_at.desc())
            .limit(20)
        )
    ).all()
    recent_actions = [
        UserActionSummaryModel(
            id=str(item.id),
            action_type=item.action_type.value if hasattr(item.action_type, "value") else str(item.action_type),
            reason=item.reason,
            created_at=item.created_at,
            moderator=await build_actor(session, server_id, item.moderator_user_id),
        )
        for item in recent_actions_rows
    ]

    base_payload = base.model_dump()
    base_payload.pop("counts", None)
    return MonitoredUserDetailsModel(
        **base_payload,
        related_cases=related_cases,
        recent_actions=recent_actions,
        counts=counts,
        comment_count=comment_count,
    )


async def add_monitored_user_from_case(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    user_id: int,
    reason: str | None,
    added_by_user_id: int,
) -> MonitoredUserReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    await build_actor(session, server_id, added_by_user_id, require_membership=True)

    valid_users = {moderation_case.target_user_id}
    linked_users = (
        await session.exec(
            select(ModerationCaseUser.user_id).where(ModerationCaseUser.case_id == case_id)
        )
    ).all()
    valid_users.update(int(item) for item in linked_users)
    if user_id not in valid_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_not_in_case",
        )

    existing = await _get_monitored_user_or_none(session, server_id, user_id)
    if existing and existing.is_active:
        return await _to_monitored_user_read(session, existing)

    now = naive_utcnow()
    if existing:
        previous_active = existing.is_active
        existing.is_active = True
        if reason is not None:
            existing.reason = reason
        existing.added_by_user_id = added_by_user_id
        existing.updated_at = now
        session.add(existing)
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

    default_reason = f"From case: {moderation_case.title}"[:200]
    item = MonitoredUser(
        server_id=server_id,
        user_id=user_id,
        added_by_user_id=added_by_user_id,
        reason=reason if reason is not None else default_reason,
        is_active=True,
        created_at=now,
        updated_at=now,
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
    session.add(
        MonitoredUserComment(
            monitored_user_id=item.id,
            author_user_id=added_by_user_id,
            comment=f"Added from case {moderation_case.title} ({case_id})",
        )
    )
    await session.flush()
    await session.refresh(item)
    return await _to_monitored_user_read(session, item)


_EVENT_OVERRIDE_FIELD = {
    "rejoin": "notify_rejoin",
    "message": "notify_messages",
    "image": "notify_images",
    "voice_join": "notify_voice",
    "thread_create": "notify_threads",
    "bot_command": "notify_commands",
    "ai_interaction": "notify_ai_interactions",
}


def _defaults_from_settings(settings: ServerMonitoringSettings) -> MonitoringEventDefaultsModel:
    return MonitoringEventDefaultsModel(
        notify_rejoin=settings.default_notify_rejoin,
        notify_messages=settings.default_notify_messages,
        message_threshold=settings.default_message_threshold,
        notify_images=settings.default_notify_images,
        notify_voice=settings.default_notify_voice,
        notify_threads=settings.default_notify_threads,
        notify_commands=settings.default_notify_commands,
        notify_ai_interactions=settings.default_notify_ai_interactions,
    )


def _overrides_from_row(row: MonitoredUserNotificationSettings | None) -> MonitoringEventOverridesModel:
    if row is None:
        return MonitoringEventOverridesModel()
    return MonitoringEventOverridesModel(
        notify_rejoin=row.notify_rejoin,
        notify_messages=row.notify_messages,
        message_threshold=row.message_threshold,
        notify_images=row.notify_images,
        notify_voice=row.notify_voice,
        notify_threads=row.notify_threads,
        notify_commands=row.notify_commands,
        notify_ai_interactions=row.notify_ai_interactions,
    )


def _effective_settings(
    defaults: MonitoringEventDefaultsModel,
    overrides: MonitoringEventOverridesModel,
) -> MonitoringEventDefaultsModel:
    values = defaults.model_dump()
    for key, value in overrides.model_dump().items():
        if value is not None:
            values[key] = value
    return MonitoringEventDefaultsModel(**values)


async def get_or_create_server_monitoring_settings(
    session: AsyncSession,
    server_id: int,
    server_name: str | None = None,
) -> ServerMonitoringSettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=server_name or str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerMonitoringSettings, server_id)
    if settings:
        return settings

    settings = ServerMonitoringSettings(server_id=server_id)
    session.add(settings)
    await session.flush()
    return settings


def to_server_monitoring_settings_read_model(
    settings: ServerMonitoringSettings,
) -> ServerMonitoringSettingsReadModel:
    return ServerMonitoringSettingsReadModel(
        server_id=str(settings.server_id),
        notification_channel_id=(
            str(settings.notification_channel_id) if settings.notification_channel_id is not None else None
        ),
        discord_notifications_enabled=settings.discord_notifications_enabled,
        defaults=_defaults_from_settings(settings),
        auto_monitor_enabled=settings.auto_monitor_enabled,
        auto_monitor_recent_account_days=settings.auto_monitor_recent_account_days,
        auto_monitor_no_avatar=settings.auto_monitor_no_avatar,
        auto_monitor_reason=settings.auto_monitor_reason,
        updated_at=settings.updated_at,
    )


async def update_server_monitoring_settings(
    session: AsyncSession,
    server_id: int,
    body: ServerMonitoringSettingsUpdateModel,
) -> ServerMonitoringSettingsReadModel:
    settings = await get_or_create_server_monitoring_settings(session, server_id)

    if "notification_channel_id" in body.model_fields_set:
        if body.notification_channel_id:
            requested_channel_id = int(body.notification_channel_id)
            channel = await fetch_channel(server_id=server_id, channel_id=requested_channel_id)
            if not channel:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="notification_channel_id is not a channel in this server",
                )
            channel_type = channel.get("type")
            if channel_type not in TEXT_CHANNEL_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="notification_channel_id must be a text or announcement channel",
                )
            settings.notification_channel_id = requested_channel_id
        else:
            settings.notification_channel_id = None
    if body.discord_notifications_enabled is not None:
        settings.discord_notifications_enabled = body.discord_notifications_enabled
    if body.defaults is not None:
        defaults = body.defaults
        settings.default_notify_rejoin = defaults.notify_rejoin
        settings.default_notify_messages = defaults.notify_messages
        settings.default_message_threshold = defaults.message_threshold
        settings.default_notify_images = defaults.notify_images
        settings.default_notify_voice = defaults.notify_voice
        settings.default_notify_threads = defaults.notify_threads
        settings.default_notify_commands = defaults.notify_commands
        settings.default_notify_ai_interactions = defaults.notify_ai_interactions
    if body.auto_monitor_enabled is not None:
        settings.auto_monitor_enabled = body.auto_monitor_enabled
    if body.auto_monitor_recent_account_days is not None:
        settings.auto_monitor_recent_account_days = body.auto_monitor_recent_account_days
    if body.auto_monitor_no_avatar is not None:
        settings.auto_monitor_no_avatar = body.auto_monitor_no_avatar
    if body.auto_monitor_reason is not None:
        settings.auto_monitor_reason = body.auto_monitor_reason.strip()

    settings.updated_at = naive_utcnow()
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return to_server_monitoring_settings_read_model(settings)


async def get_monitored_user_notification_settings(
    session: AsyncSession,
    server_id: int,
    user_id: int,
) -> MonitoredUserNotificationSettingsReadModel:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")
    settings = await get_or_create_server_monitoring_settings(session, server_id)
    row = await session.get(MonitoredUserNotificationSettings, monitored_user.id)
    overrides = _overrides_from_row(row)
    return MonitoredUserNotificationSettingsReadModel(
        monitored_user_id=str(monitored_user.id),
        effective=_effective_settings(_defaults_from_settings(settings), overrides),
        overrides=overrides,
        updated_at=row.updated_at if row else None,
    )


async def update_monitored_user_notification_settings(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    body: MonitoredUserNotificationSettingsUpdateModel,
) -> MonitoredUserNotificationSettingsReadModel:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")
    row = await session.get(MonitoredUserNotificationSettings, monitored_user.id)
    if row is None:
        row = MonitoredUserNotificationSettings(monitored_user_id=monitored_user.id)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_at = naive_utcnow()
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return await get_monitored_user_notification_settings(session, server_id, user_id)


def _to_activity_event_read(
    item: MonitoredUserActivityEvent,
    user=None,
) -> MonitoredUserActivityEventReadModel:
    return MonitoredUserActivityEventReadModel(
        id=str(item.id),
        monitored_user_id=str(item.monitored_user_id),
        server_id=str(item.server_id),
        user_id=str(item.user_id),
        event_type=item.event_type,
        channel_id=str(item.channel_id) if item.channel_id is not None else None,
        message_id=str(item.message_id) if item.message_id is not None else None,
        message_content=item.message_content,
        metadata=item.metadata_json or {},
        notification_sent=item.notification_sent,
        occurred_at=item.occurred_at,
        user=user,
    )


async def list_monitored_user_activity_events(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
) -> list[MonitoredUserActivityEventReadModel]:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user:
        raise LookupError("Monitored user not found")
    rows = (
        await session.exec(
            select(MonitoredUserActivityEvent)
            .where(MonitoredUserActivityEvent.monitored_user_id == monitored_user.id)
            .order_by(MonitoredUserActivityEvent.occurred_at.desc())
            .limit(limit)
        )
    ).all()
    actor = await build_actor(session, server_id, user_id)
    return [_to_activity_event_read(row, actor) for row in rows]


async def get_monitoring_notification_channel_id(
    session: AsyncSession,
    server_id: int,
) -> int | None:
    settings = await get_or_create_server_monitoring_settings(session, server_id)
    if not settings.discord_notifications_enabled:
        return None
    if settings.notification_channel_id is not None:
        return settings.notification_channel_id
    mod_settings = await session.get(ServerModerationSettings, server_id)
    return mod_settings.mod_log_channel_id if mod_settings else None


async def mark_monitoring_activity_notification_sent(
    session: AsyncSession,
    event_id: UUID,
) -> None:
    event = await session.get(MonitoredUserActivityEvent, event_id)
    if event is None:
        return
    event.notification_sent = True
    session.add(event)
    await session.flush()


async def record_monitored_user_activity(
    session: AsyncSession,
    *,
    server_id: int,
    user_id: int,
    event_type: str,
    channel_id: int | None = None,
    message_id: int | None = None,
    message_content: str | None = None,
    metadata: dict | None = None,
) -> tuple[MonitoredUserActivityEvent | None, bool]:
    monitored_user = await _get_monitored_user_or_none(session, server_id, user_id)
    if not monitored_user or not monitored_user.is_active:
        return None, False

    event = MonitoredUserActivityEvent(
        monitored_user_id=monitored_user.id,
        server_id=server_id,
        user_id=user_id,
        event_type=event_type,
        channel_id=channel_id,
        message_id=message_id,
        message_content=(message_content or None),
        metadata_json=metadata or {},
    )
    session.add(event)
    monitored_user.updated_at = naive_utcnow()
    session.add(monitored_user)
    await session.flush()

    server_settings = await get_or_create_server_monitoring_settings(session, server_id)
    if not server_settings.discord_notifications_enabled:
        return event, False

    override_row = await session.get(MonitoredUserNotificationSettings, monitored_user.id)
    effective = _effective_settings(_defaults_from_settings(server_settings), _overrides_from_row(override_row))
    notify_field = _EVENT_OVERRIDE_FIELD.get(event_type)
    if notify_field is None:
        return event, False
    if not getattr(effective, notify_field):
        return event, False

    if event_type == "message":
        message_count = int(
            (
                await session.exec(
                    select(func.count())
                    .select_from(MonitoredUserActivityEvent)
                    .where(
                        MonitoredUserActivityEvent.monitored_user_id == monitored_user.id,
                        MonitoredUserActivityEvent.event_type == "message",
                    )
                )
            ).one()
            or 0
        )
        threshold = max(1, effective.message_threshold)
        if message_count % threshold != 0:
            return event, False
        event.metadata_json = {**(event.metadata_json or {}), "message_count": message_count, "threshold": threshold}
        session.add(event)
        await session.flush()

    return event, True


async def maybe_auto_monitor_new_member(
    session: AsyncSession,
    *,
    member,
) -> MonitoredUserReadModel | None:
    if getattr(member, "bot", False) or getattr(member, "guild", None) is None:
        return None
    server_id = int(member.guild.id)
    settings = await get_or_create_server_monitoring_settings(session, server_id)
    if not settings.auto_monitor_enabled:
        return None

    signals: list[str] = []
    account_created_at = getattr(member, "created_at", None)
    if account_created_at is not None:
        account_age_days = (datetime.now(account_created_at.tzinfo) - account_created_at).days
        if account_age_days <= settings.auto_monitor_recent_account_days:
            signals.append(f"account_age_days={account_age_days}")
    if settings.auto_monitor_no_avatar and getattr(member, "avatar", None) is None:
        signals.append("no_avatar")
    if not signals:
        return None

    reason = f"{settings.auto_monitor_reason}: {', '.join(signals)}"
    return await upsert_monitored_user(
        session=session,
        server_id=server_id,
        user_id=int(member.id),
        reason=reason[:5000],
        added_by_user_id=int(member.id),
        source="auto",
    )

