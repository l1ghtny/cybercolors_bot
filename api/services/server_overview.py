from datetime import datetime, timezone

from sqlalchemy import distinct, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.server_overview import (
    ServerOverviewModel,
    ServerOverviewSetupModel,
    ServerOverviewStatsModel,
    ServerTimelineEventModel,
    ServerTimelineModel,
)
from api.services.ai_moderation import count_pending_ai_suggestions
from api.services.moderation_core import (
    build_optional_actor,
    get_system_actor,
    moderation_action_is_reverted,
    naive_utcnow,
)
from src.db.models import (
    ActionType,
    Birthday,
    CaseStatus,
    DeletedMessage,
    MessageLog,
    ModerationAction,
    ModerationCase,
    ModerationCaseEvidence,
    ModerationCaseNote,
    ModerationRule,
    MonitoredUser,
    MonitoredUserStatusEvent,
    Replies,
    Server,
    ServerLocalizationSettings,
    ServerModerationSettings,
    ServerRbacAuditEvent,
    ServerSecuritySettings,
    User,
)


def _today_start_utc() -> datetime:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def _count(session: AsyncSession, statement) -> int:
    value = (await session.exec(statement)).one()
    return int(value or 0)


async def build_server_overview(session: AsyncSession, server_id: int) -> ServerOverviewModel:
    today_start = _today_start_utc()

    actions_today = await _count(
        session,
        select(func.count(ModerationAction.id)).where(
            ModerationAction.server_id == server_id,
            ModerationAction.created_at >= today_start,
        ),
    )
    actions_total = await _count(
        session,
        select(func.count(ModerationAction.id)).where(ModerationAction.server_id == server_id),
    )
    open_cases = await _count(
        session,
        select(func.count(ModerationCase.id)).where(
            ModerationCase.server_id == server_id,
            ModerationCase.status == CaseStatus.OPEN,
        ),
    )
    active_mutes = await _count(
        session,
        select(func.count(ModerationAction.id)).where(
            ModerationAction.server_id == server_id,
            ModerationAction.action_type == ActionType.MUTE,
            ModerationAction.is_active.is_(True),
        ),
    )
    active_monitored_users = await _count(
        session,
        select(func.count(MonitoredUser.id)).where(
            MonitoredUser.server_id == server_id,
            MonitoredUser.is_active.is_(True),
        ),
    )
    deleted_messages_today = await _count(
        session,
        select(func.count(DeletedMessage.id)).where(
            DeletedMessage.server_id == server_id,
            DeletedMessage.deleted_at >= today_start,
        ),
    )
    replies_count = await _count(
        session,
        select(func.count(Replies.id)).where(Replies.server_id == server_id),
    )
    active_rules_count = await _count(
        session,
        select(func.count(ModerationRule.id)).where(
            ModerationRule.server_id == server_id,
            ModerationRule.is_active.is_(True),
        ),
    )
    birthdays_count = await _count(
        session,
        select(func.count(Birthday.user_id))
        .select_from(User)
        .join(Birthday, Birthday.user_id == User.user_id)
        .where(User.server_id == server_id),
    )
    messages_today = await _count(
        session,
        select(func.count(MessageLog.message_id)).where(
            MessageLog.server_id == server_id,
            MessageLog.created_at >= today_start,
        ),
    )
    active_users_today = await _count(
        session,
        select(func.count(distinct(MessageLog.user_id))).where(
            MessageLog.server_id == server_id,
            MessageLog.created_at >= today_start,
        ),
    )
    last_message_at = (
        await session.exec(
            select(func.max(MessageLog.created_at)).where(MessageLog.server_id == server_id)
        )
    ).one()
    ai_pending_suggestions = await count_pending_ai_suggestions(session=session, server_id=server_id)

    server = await session.get(Server, server_id)
    moderation_settings = await session.get(ServerModerationSettings, server_id)
    security_settings = await session.get(ServerSecuritySettings, server_id)
    localization_settings = await session.get(ServerLocalizationSettings, server_id)

    return ServerOverviewModel(
        server_id=str(server_id),
        generated_at=naive_utcnow(),
        stats=ServerOverviewStatsModel(
            moderation_actions_today=actions_today,
            moderation_actions_total=actions_total,
            open_cases=open_cases,
            active_mutes=active_mutes,
            active_monitored_users=active_monitored_users,
            deleted_messages_today=deleted_messages_today,
            replies_count=replies_count,
            active_rules_count=active_rules_count,
            birthdays_count=birthdays_count,
            messages_today=messages_today,
            active_users_today=active_users_today,
            ai_pending_suggestions=ai_pending_suggestions,
            last_message_at=last_message_at,
        ),
        setup=ServerOverviewSetupModel(
            mute_role_configured=bool(moderation_settings and moderation_settings.mute_role_id),
            mod_log_channel_configured=bool(moderation_settings and moderation_settings.mod_log_channel_id),
            birthday_channel_configured=bool(server and server.birthday_channel_id),
            birthday_role_configured=bool(server and server.birthday_role_id),
            verified_role_configured=bool(security_settings and security_settings.verified_role_id),
            newcomer_role_configured=bool(security_settings and security_settings.newcomer_role_id),
            newcomer_restriction_enabled=bool(
                security_settings and security_settings.newcomer_restriction_enabled
            ),
            lockdown_enabled=bool(security_settings and security_settings.lockdown_enabled),
            locale_code=localization_settings.locale_code if localization_settings else "en",
        ),
    )


async def _action_events(session: AsyncSession, server_id: int, limit: int) -> list[ServerTimelineEventModel]:
    actions = (
        await session.exec(
            select(ModerationAction)
            .where(ModerationAction.server_id == server_id)
            .order_by(ModerationAction.created_at.desc())
            .limit(limit)
        )
    ).all()
    events: list[ServerTimelineEventModel] = []
    for action in actions:
        action_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        events.append(
            ServerTimelineEventModel(
                id=f"moderation_action:{action.id}",
                server_id=str(server_id),
                event_type="moderation_action_created",
                entity_type="moderation_action",
                entity_id=str(action.id),
                occurred_at=action.created_at,
                title=f"{action_type.title()} action recorded",
                description=action.reason,
                actor=await build_optional_actor(session, server_id, action.moderator_user_id),
                target=await build_optional_actor(session, server_id, action.target_user_id),
                metadata={
                    "action_type": action_type,
                    "case_id": str(action.case_id) if action.case_id else None,
                    "rule_id": str(action.rule_id) if action.rule_id else None,
                    "is_active": action.is_active,
                    "is_reverted": moderation_action_is_reverted(action.action_type, action.is_active),
                },
            )
        )
    return events


async def _case_events(session: AsyncSession, server_id: int, limit: int) -> list[ServerTimelineEventModel]:
    cases = (
        await session.exec(
            select(ModerationCase)
            .where(ModerationCase.server_id == server_id)
            .order_by(ModerationCase.created_at.desc())
            .limit(limit)
        )
    ).all()
    events: list[ServerTimelineEventModel] = []
    for moderation_case in cases:
        events.append(
            ServerTimelineEventModel(
                id=f"moderation_case_opened:{moderation_case.id}",
                server_id=str(server_id),
                event_type="moderation_case_opened",
                entity_type="moderation_case",
                entity_id=str(moderation_case.id),
                occurred_at=moderation_case.created_at,
                title=f"Case opened: {moderation_case.title}",
                description=moderation_case.summary,
                actor=await build_optional_actor(session, server_id, moderation_case.opened_by_user_id),
                target=await build_optional_actor(session, server_id, moderation_case.target_user_id),
                metadata={"status": moderation_case.status.value},
            )
        )
        if moderation_case.closed_at is not None:
            event_type = "moderation_case_archived" if moderation_case.status == CaseStatus.ARCHIVED else "moderation_case_closed"
            title = "Case archived" if moderation_case.status == CaseStatus.ARCHIVED else "Case closed"
            events.append(
                ServerTimelineEventModel(
                    id=f"{event_type}:{moderation_case.id}",
                    server_id=str(server_id),
                    event_type=event_type,
                    entity_type="moderation_case",
                    entity_id=str(moderation_case.id),
                    occurred_at=moderation_case.closed_at,
                    title=f"{title}: {moderation_case.title}",
                    description=moderation_case.summary,
                    actor=await build_optional_actor(session, server_id, moderation_case.closed_by_user_id),
                    target=await build_optional_actor(session, server_id, moderation_case.target_user_id),
                    metadata={"status": moderation_case.status.value},
                )
            )
    return events


async def _monitoring_events(session: AsyncSession, server_id: int, limit: int) -> list[ServerTimelineEventModel]:
    rows = (
        await session.exec(
            select(MonitoredUserStatusEvent, MonitoredUser)
            .join(MonitoredUser, MonitoredUser.id == MonitoredUserStatusEvent.monitored_user_id)
            .where(MonitoredUser.server_id == server_id)
            .order_by(MonitoredUserStatusEvent.changed_at.desc())
            .limit(limit)
        )
    ).all()
    events: list[ServerTimelineEventModel] = []
    for status_event, monitored_user in rows:
        title = "Monitoring enabled" if status_event.to_is_active else "Monitoring disabled"
        events.append(
            ServerTimelineEventModel(
                id=f"monitored_status:{status_event.id}",
                server_id=str(server_id),
                event_type="monitored_user_status_changed",
                entity_type="monitored_user",
                entity_id=str(monitored_user.id),
                occurred_at=status_event.changed_at,
                title=title,
                description=monitored_user.reason,
                actor=await build_optional_actor(session, server_id, status_event.changed_by_user_id),
                target=await build_optional_actor(session, server_id, monitored_user.user_id),
                metadata={
                    "from_is_active": status_event.from_is_active,
                    "to_is_active": status_event.to_is_active,
                },
            )
        )
    return events


async def _case_note_events(session: AsyncSession, server_id: int, limit: int) -> list[ServerTimelineEventModel]:
    rows = (
        await session.exec(
            select(ModerationCaseNote, ModerationCase)
            .join(ModerationCase, ModerationCase.id == ModerationCaseNote.case_id)
            .where(ModerationCase.server_id == server_id)
            .order_by(ModerationCaseNote.created_at.desc())
            .limit(limit)
        )
    ).all()
    events: list[ServerTimelineEventModel] = []
    for note, moderation_case in rows:
        events.append(
            ServerTimelineEventModel(
                id=f"case_note:{note.id}",
                server_id=str(server_id),
                event_type="moderation_case_note_added",
                entity_type="moderation_case_note",
                entity_id=str(note.id),
                occurred_at=note.created_at,
                title=f"Case note added: {moderation_case.title}",
                description=note.note,
                actor=await build_optional_actor(session, server_id, note.author_user_id) or get_system_actor(),
                target=await build_optional_actor(session, server_id, moderation_case.target_user_id),
                metadata={
                    "case_id": str(moderation_case.id),
                    "is_internal": note.is_internal,
                },
            )
        )
    return events


async def _case_evidence_events(session: AsyncSession, server_id: int, limit: int) -> list[ServerTimelineEventModel]:
    rows = (
        await session.exec(
            select(ModerationCaseEvidence, ModerationCase)
            .join(ModerationCase, ModerationCase.id == ModerationCaseEvidence.case_id)
            .where(ModerationCase.server_id == server_id)
            .order_by(ModerationCaseEvidence.created_at.desc())
            .limit(limit)
        )
    ).all()
    events: list[ServerTimelineEventModel] = []
    for evidence, moderation_case in rows:
        evidence_type = evidence.evidence_type.value if hasattr(evidence.evidence_type, "value") else str(evidence.evidence_type)
        events.append(
            ServerTimelineEventModel(
                id=f"case_evidence:{evidence.id}",
                server_id=str(server_id),
                event_type="moderation_case_evidence_added",
                entity_type="moderation_case_evidence",
                entity_id=str(evidence.id),
                occurred_at=evidence.created_at,
                title=f"Case evidence added: {moderation_case.title}",
                description=evidence.text or evidence.url or evidence.attachment_key,
                actor=await build_optional_actor(session, server_id, evidence.added_by_user_id),
                target=await build_optional_actor(session, server_id, moderation_case.target_user_id),
                metadata={
                    "case_id": str(moderation_case.id),
                    "evidence_type": evidence_type,
                },
            )
        )
    return events


async def _rbac_audit_events(session: AsyncSession, server_id: int, limit: int) -> list[ServerTimelineEventModel]:
    audit_events = (
        await session.exec(
            select(ServerRbacAuditEvent)
            .where(ServerRbacAuditEvent.server_id == server_id)
            .order_by(ServerRbacAuditEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    events: list[ServerTimelineEventModel] = []
    for audit_event in audit_events:
        if audit_event.before_json is None and audit_event.after_json is not None:
            title = "RBAC assignment created"
        elif audit_event.after_json is None:
            title = "RBAC assignment removed"
        else:
            title = "RBAC assignment updated"

        target = None
        if audit_event.subject_type == "user" and audit_event.subject_id.isdigit():
            target = await build_optional_actor(session, server_id, int(audit_event.subject_id))

        events.append(
            ServerTimelineEventModel(
                id=f"rbac_assignment:{audit_event.id}",
                server_id=str(server_id),
                event_type="rbac_assignment_changed",
                entity_type="server_rbac_assignment",
                entity_id=str(audit_event.id),
                occurred_at=audit_event.created_at,
                title=title,
                description=f"{audit_event.subject_type}:{audit_event.subject_id}",
                actor=await build_optional_actor(session, server_id, audit_event.actor_user_id),
                target=target,
                metadata={
                    "subject_type": audit_event.subject_type,
                    "subject_id": audit_event.subject_id,
                    "before": audit_event.before_json,
                    "after": audit_event.after_json,
                },
            )
        )
    return events


async def build_server_timeline(session: AsyncSession, server_id: int, limit: int = 100) -> ServerTimelineModel:
    scoped_limit = max(1, min(limit, 200))
    events: list[ServerTimelineEventModel] = []
    events.extend(await _action_events(session, server_id, scoped_limit))
    events.extend(await _case_events(session, server_id, scoped_limit))
    events.extend(await _monitoring_events(session, server_id, scoped_limit))
    events.extend(await _case_note_events(session, server_id, scoped_limit))
    events.extend(await _case_evidence_events(session, server_id, scoped_limit))
    events.extend(await _rbac_audit_events(session, server_id, scoped_limit))
    events.sort(key=lambda item: item.occurred_at, reverse=True)
    return ServerTimelineModel(
        server_id=str(server_id),
        generated_at=naive_utcnow(),
        events=events[:scoped_limit],
    )
