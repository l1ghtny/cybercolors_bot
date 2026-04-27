from datetime import datetime
from pathlib import Path
from typing import List
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionCreate, ModerationActionRead
from api.models.moderation_cases import (
    ModerationCaseCreateModel,
    ModerationCaseDetailsModel,
    ModerationCaseEvidenceCreateModel,
    ModerationCaseEvidenceReadModel,
    ModerationCaseLinkedUserSummaryModel,
    ModerationCaseListStatsModel,
    ModerationCaseNoteCreateModel,
    ModerationCaseNoteReadModel,
    ModerationCaseReadModel,
    ModerationCaseSummaryModel,
    ModerationCaseRulesUpsertModel,
    ModerationCaseActionCreateFromCaseModel,
    ModerationCaseStatusUpdateModel,
    ModerationCaseUserReadModel,
    ModerationActorModel,
)
from api.services.moderation_actions_service import create_action
from api.services.moderation_core import (
    build_actor,
    get_case_or_404,
    get_system_actor,
    naive_utcnow,
    to_case_read,
    to_moderation_history,
)
from src.db.models import (
    CaseStatus,
    CaseUserRole,
    ModerationAction,
    ModerationActionRuleCitation,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseEvidence,
    ModerationCaseNote,
    ModerationCaseRuleCitation,
    ModerationCaseUser,
    MonitoredUser,
    User,
    Server,
    GlobalUser,
    ModerationRule,
)

EVIDENCE_UPLOAD_ROOT = Path("logs") / "moderation_evidence"


def safe_upload_key(server_id: int, case_id: UUID, filename: str) -> str:
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()[:10]
    return f"{server_id}_{case_id}_{uuid4().hex}{ext}"


def _parse_rule_ids(rule_ids: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    seen: set[UUID] = set()
    for raw_rule_id in rule_ids:
        if not raw_rule_id:
            continue
        try:
            parsed_rule_id = UUID(str(raw_rule_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid rule id: {raw_rule_id}",
            )
        if parsed_rule_id in seen:
            continue
        seen.add(parsed_rule_id)
        parsed.append(parsed_rule_id)
    return parsed


async def _resolve_case_rules(
    session: AsyncSession,
    server_id: int,
    rule_ids: list[UUID],
) -> list[ModerationRule]:
    if not rule_ids:
        return []
    rules = (
        await session.exec(
            select(ModerationRule).where(
                ModerationRule.server_id == server_id,
                ModerationRule.id.in_(rule_ids),
                ModerationRule.is_active.is_(True),
            )
        )
    ).all()
    by_id = {rule.id: rule for rule in rules}
    missing = [rule_id for rule_id in rule_ids if rule_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Moderation rule not found",
        )
    return [by_id[rule_id] for rule_id in rule_ids]


async def _upsert_case_rule_citations(
    session: AsyncSession,
    moderation_case: ModerationCase,
    rules: list[ModerationRule],
    cited_at: datetime | None = None,
) -> None:
    if not rules:
        return

    existing = (
        await session.exec(
            select(ModerationCaseRuleCitation).where(
                ModerationCaseRuleCitation.case_id == moderation_case.id,
                ModerationCaseRuleCitation.rule_id.in_([rule.id for rule in rules]),
            )
        )
    ).all()
    existing_rule_ids = {item.rule_id for item in existing if item.rule_id is not None}
    citation_time = cited_at or moderation_case.created_at

    for rule in rules:
        if rule.id in existing_rule_ids:
            continue
        session.add(
            ModerationCaseRuleCitation(
                case_id=moderation_case.id,
                rule_id=rule.id,
                server_id=moderation_case.server_id,
                rule_code_snapshot=rule.code,
                rule_title_snapshot=rule.title,
                cited_at=citation_time,
            )
        )
    await session.flush()


async def _add_case_system_note_for_monitored_subjects(
    session: AsyncSession,
    moderation_case: ModerationCase,
    subject_user_ids: set[int] | None = None,
) -> None:
    scoped_user_ids = subject_user_ids if subject_user_ids else {moderation_case.target_user_id}
    monitored_subjects = (
        await session.exec(
            select(MonitoredUser, GlobalUser)
            .join(GlobalUser, GlobalUser.discord_id == MonitoredUser.user_id)
            .where(
                MonitoredUser.server_id == moderation_case.server_id,
                MonitoredUser.user_id.in_(list(scoped_user_ids)),
                MonitoredUser.is_active.is_(True),
            )
            .order_by(MonitoredUser.created_at.asc())
        )
    ).all()
    for monitored_user, global_user in monitored_subjects:
        display_name = global_user.username or str(monitored_user.user_id)
        reason = monitored_user.reason or "no reason given"
        note_text = (
            f"Subject {display_name} is on the watchlist since "
            f"{monitored_user.created_at:%Y-%m-%d} - reason: {reason}"
        )
        session.add(
            ModerationCaseNote(
                case_id=moderation_case.id,
                author_user_id=None,
                note=note_text,
                is_internal=True,
            )
        )
    if monitored_subjects:
        await session.flush()


async def _list_case_rule_ids(session: AsyncSession, case_id: UUID) -> list[str]:
    rows = (
        await session.exec(
            select(ModerationCaseRuleCitation.rule_id)
            .where(
                ModerationCaseRuleCitation.case_id == case_id,
                ModerationCaseRuleCitation.rule_id.is_not(None),
            )
        )
    ).all()
    return [str(rule_id) for rule_id in rows if rule_id is not None]


async def _build_actor_map(
    session: AsyncSession,
    server_id: int,
    user_ids: set[int],
) -> dict[int, ModerationActorModel]:
    if not user_ids:
        return {}

    global_users = (
        await session.exec(
            select(GlobalUser).where(GlobalUser.discord_id.in_(list(user_ids)))
        )
    ).all()
    memberships = (
        await session.exec(
            select(User).where(
                User.server_id == server_id,
                User.user_id.in_(list(user_ids)),
            )
        )
    ).all()

    global_by_id = {item.discord_id: item for item in global_users}
    membership_by_id = {item.user_id: item for item in memberships}
    actors: dict[int, ModerationActorModel] = {}

    for user_id in user_ids:
        global_user = global_by_id.get(user_id)
        membership = membership_by_id.get(user_id)
        display_name = (
            membership.server_nickname
            if membership and membership.server_nickname
            else (global_user.username if global_user and global_user.username else str(user_id))
        )
        actors[user_id] = ModerationActorModel(
            user_id=str(user_id),
            username=global_user.username if global_user else None,
            server_nickname=membership.server_nickname if membership else None,
            display_name=display_name,
            avatar_hash=global_user.avatar_hash if global_user else None,
        )
    return actors


async def _count_case_actions(
    session: AsyncSession,
    server_id: int,
    case_ids: list[UUID],
) -> dict[UUID, int]:
    if not case_ids:
        return {}

    action_ids_by_case: dict[UUID, set[UUID]] = {}

    primary_pairs = (
        await session.exec(
            select(ModerationAction.case_id, ModerationAction.id).where(
                ModerationAction.server_id == server_id,
                ModerationAction.case_id.in_(case_ids),
            )
        )
    ).all()
    for case_id, action_id in primary_pairs:
        if case_id is None:
            continue
        action_ids_by_case.setdefault(case_id, set()).add(action_id)

    linked_pairs = (
        await session.exec(
            select(ModerationCaseActionLink.case_id, ModerationCaseActionLink.moderation_action_id)
            .join(
                ModerationAction,
                ModerationAction.id == ModerationCaseActionLink.moderation_action_id,
            )
            .where(
                ModerationCaseActionLink.case_id.in_(case_ids),
                ModerationAction.server_id == server_id,
            )
        )
    ).all()
    for case_id, action_id in linked_pairs:
        action_ids_by_case.setdefault(case_id, set()).add(action_id)

    return {case_id: len(action_ids) for case_id, action_ids in action_ids_by_case.items()}


async def _count_case_entities(
    session: AsyncSession,
    case_ids: list[UUID],
) -> tuple[dict[UUID, int], dict[UUID, int], dict[UUID, int]]:
    if not case_ids:
        return {}, {}, {}

    rule_counts_rows = (
        await session.exec(
            select(
                ModerationCaseRuleCitation.case_id,
                func.count(ModerationCaseRuleCitation.id),
            )
            .where(ModerationCaseRuleCitation.case_id.in_(case_ids))
            .group_by(ModerationCaseRuleCitation.case_id)
        )
    ).all()
    note_counts_rows = (
        await session.exec(
            select(
                ModerationCaseNote.case_id,
                func.count(ModerationCaseNote.id),
            )
            .where(ModerationCaseNote.case_id.in_(case_ids))
            .group_by(ModerationCaseNote.case_id)
        )
    ).all()
    evidence_counts_rows = (
        await session.exec(
            select(
                ModerationCaseEvidence.case_id,
                func.count(ModerationCaseEvidence.id),
            )
            .where(ModerationCaseEvidence.case_id.in_(case_ids))
            .group_by(ModerationCaseEvidence.case_id)
        )
    ).all()

    rule_counts = {case_id: int(count or 0) for case_id, count in rule_counts_rows}
    note_counts = {case_id: int(count or 0) for case_id, count in note_counts_rows}
    evidence_counts = {case_id: int(count or 0) for case_id, count in evidence_counts_rows}
    return rule_counts, note_counts, evidence_counts


async def create_case(
    session: AsyncSession,
    server_id: int,
    body: ModerationCaseCreateModel,
    opened_by_user_id: int,
) -> ModerationCaseReadModel:
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    target_user_id = int(body.target_user_id)
    await build_actor(session, server_id, target_user_id, require_membership=True)
    await build_actor(session, server_id, opened_by_user_id, require_membership=True)

    moderation_case = ModerationCase(
        server_id=server_id,
        target_user_id=target_user_id,
        opened_by_user_id=opened_by_user_id,
        title=body.title,
        summary=body.summary,
        status=CaseStatus.OPEN,
    )
    session.add(moderation_case)
    await session.flush()
    session.add(
        ModerationCaseUser(
            case_id=moderation_case.id,
            user_id=target_user_id,
            role=CaseUserRole.PRIMARY_TARGET,
            added_by_user_id=opened_by_user_id,
        )
    )

    additional_user_ids: set[int] = set()
    for raw_user_id in body.users:
        if raw_user_id and raw_user_id.isdigit():
            parsed_user_id = int(raw_user_id)
            if parsed_user_id != target_user_id:
                additional_user_ids.add(parsed_user_id)
    for related_user_id in additional_user_ids:
        await build_actor(session, server_id, related_user_id)
        session.add(
            ModerationCaseUser(
                case_id=moderation_case.id,
                user_id=related_user_id,
                role=CaseUserRole.RELATED,
                added_by_user_id=opened_by_user_id,
            )
        )

    parsed_rule_ids = _parse_rule_ids(body.rule_ids or [])
    resolved_rules = await _resolve_case_rules(session=session, server_id=server_id, rule_ids=parsed_rule_ids)
    await _upsert_case_rule_citations(
        session=session,
        moderation_case=moderation_case,
        rules=resolved_rules,
    )

    await _add_case_system_note_for_monitored_subjects(
        session=session,
        moderation_case=moderation_case,
        subject_user_ids={target_user_id, *additional_user_ids},
    )

    await session.flush()
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def list_cases(
    session: AsyncSession,
    server_id: int,
    status_filter: CaseStatus | None = None,
    target_user_id: str | None = None,
    user_id: str | None = None,
    limit: int | None = None,
) -> list[ModerationCaseSummaryModel]:
    statement = select(ModerationCase).where(ModerationCase.server_id == server_id)
    if status_filter:
        statement = statement.where(ModerationCase.status == status_filter)
    if target_user_id:
        statement = statement.where(ModerationCase.target_user_id == int(target_user_id))
    if user_id:
        resolved_user_id = int(user_id)
        statement = statement.where(
            or_(
                ModerationCase.target_user_id == resolved_user_id,
                ModerationCase.id.in_(
                    select(ModerationCaseUser.case_id).where(ModerationCaseUser.user_id == resolved_user_id)
                ),
            )
        )

    statement = statement.order_by(ModerationCase.created_at.desc())
    if limit is not None:
        statement = statement.limit(limit)
    cases = (await session.exec(statement)).all()
    if not cases:
        return []

    case_ids = [item.id for item in cases if item.id is not None]
    if not case_ids:
        return []

    case_user_links = (
        await session.exec(
            select(ModerationCaseUser)
            .where(ModerationCaseUser.case_id.in_(case_ids))
            .order_by(ModerationCaseUser.added_at.asc())
        )
    ).all()
    links_by_case: dict[UUID, list[ModerationCaseUser]] = {}
    all_actor_ids: set[int] = set()
    for item in cases:
        all_actor_ids.add(item.target_user_id)
        all_actor_ids.add(item.opened_by_user_id)
        if item.closed_by_user_id is not None:
            all_actor_ids.add(item.closed_by_user_id)
    for link in case_user_links:
        links_by_case.setdefault(link.case_id, []).append(link)
        all_actor_ids.add(link.user_id)

    actors = await _build_actor_map(session=session, server_id=server_id, user_ids=all_actor_ids)
    action_counts = await _count_case_actions(session=session, server_id=server_id, case_ids=case_ids)
    rule_counts, note_counts, evidence_counts = await _count_case_entities(session=session, case_ids=case_ids)

    summaries: list[ModerationCaseSummaryModel] = []
    for item in cases:
        if item.id is None:
            continue
        linked_users = [
            ModerationCaseLinkedUserSummaryModel(
                user=actors[link.user_id],
                role=link.role,
            )
            for link in links_by_case.get(item.id, [])
            if link.user_id in actors
        ]
        summaries.append(
            ModerationCaseSummaryModel(
                id=str(item.id),
                server_id=str(item.server_id),
                title=item.title,
                summary=item.summary,
                status=item.status,
                created_at=item.created_at,
                closed_at=item.closed_at,
                target_user=actors[item.target_user_id],
                opened_by=actors[item.opened_by_user_id],
                closed_by=actors.get(item.closed_by_user_id) if item.closed_by_user_id is not None else None,
                linked_users=linked_users,
                stats=ModerationCaseListStatsModel(
                    linked_users_count=len(linked_users),
                    linked_actions_count=action_counts.get(item.id, 0),
                    rules_count=rule_counts.get(item.id, 0),
                    notes_count=note_counts.get(item.id, 0),
                    evidence_count=evidence_counts.get(item.id, 0),
                ),
            )
        )
    return summaries


async def get_case_details(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
) -> ModerationCaseDetailsModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    case_data = await to_case_read(moderation_case, session)

    notes = (
        await session.exec(
            select(ModerationCaseNote)
            .where(ModerationCaseNote.case_id == case_id)
            .order_by(ModerationCaseNote.created_at.desc())
        )
    ).all()
    note_rows: list[ModerationCaseNoteReadModel] = []
    for note in notes:
        author = (
            await build_actor(session, server_id, note.author_user_id)
            if note.author_user_id is not None
            else get_system_actor()
        )
        note_rows.append(
            ModerationCaseNoteReadModel(
                id=str(note.id),
                case_id=str(note.case_id),
                note=note.note,
                is_internal=note.is_internal,
                created_at=note.created_at,
                author=author,
            )
        )

    evidence_items = (
        await session.exec(
            select(ModerationCaseEvidence)
            .where(ModerationCaseEvidence.case_id == case_id)
            .order_by(ModerationCaseEvidence.created_at.desc())
        )
    ).all()
    evidence_rows: list[ModerationCaseEvidenceReadModel] = []
    for evidence in evidence_items:
        added_by = await build_actor(session, server_id, evidence.added_by_user_id)
        evidence_rows.append(
            ModerationCaseEvidenceReadModel(
                id=str(evidence.id),
                case_id=str(evidence.case_id),
                evidence_type=evidence.evidence_type,
                url=evidence.url,
                text=evidence.text,
                attachment_key=evidence.attachment_key,
                created_at=evidence.created_at,
                added_by=added_by,
            )
        )

    return ModerationCaseDetailsModel(
        case=case_data,
        notes=note_rows,
        evidence=evidence_rows,
        linked_actions=case_data.linked_action_ids,
        linked_action_ids=case_data.linked_action_ids,
        linked_action_summaries=case_data.linked_actions,
    )


async def update_case_status(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    body: ModerationCaseStatusUpdateModel,
    closed_by_user_id: int | None,
) -> ModerationCaseReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)

    if body.status == CaseStatus.OPEN:
        moderation_case.status = CaseStatus.OPEN
        moderation_case.closed_at = None
        moderation_case.closed_by_user_id = None
    else:
        if closed_by_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="closed_by_user_id is required when closing or archiving a case",
            )
        await build_actor(session, server_id, closed_by_user_id, require_membership=True)
        moderation_case.status = body.status
        moderation_case.closed_at = naive_utcnow()
        moderation_case.closed_by_user_id = closed_by_user_id

    session.add(moderation_case)
    await session.flush()
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def list_case_users(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
) -> list[ModerationCaseUserReadModel]:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    case_data = await to_case_read(moderation_case, session)
    return case_data.users


async def add_user_to_case(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    user_id: int,
    role: CaseUserRole,
    added_by_user_id: int,
) -> ModerationCaseReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    await build_actor(session, server_id, user_id)
    await build_actor(session, server_id, added_by_user_id, require_membership=True)

    existing_link = (
        await session.exec(
            select(ModerationCaseUser).where(
                ModerationCaseUser.case_id == case_id,
                ModerationCaseUser.user_id == user_id,
            )
        )
    ).first()

    if role == CaseUserRole.PRIMARY_TARGET:
        existing_primary = (
            await session.exec(
                select(ModerationCaseUser).where(
                    ModerationCaseUser.case_id == case_id,
                    ModerationCaseUser.role == CaseUserRole.PRIMARY_TARGET,
                )
            )
        ).first()
        if existing_primary and existing_primary.user_id != user_id:
            existing_primary.role = CaseUserRole.TARGET
            session.add(existing_primary)
        moderation_case.target_user_id = user_id
        session.add(moderation_case)

    if existing_link:
        existing_link.role = role
        session.add(existing_link)
    else:
        session.add(
            ModerationCaseUser(
                case_id=case_id,
                user_id=user_id,
                role=role,
                added_by_user_id=added_by_user_id,
            )
        )

    await session.flush()
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def remove_user_from_case(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    user_id: int,
) -> ModerationCaseReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    link = (
        await session.exec(
            select(ModerationCaseUser).where(
                ModerationCaseUser.case_id == case_id,
                ModerationCaseUser.user_id == user_id,
            )
        )
    ).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case user not found")
    if link.role == CaseUserRole.PRIMARY_TARGET or moderation_case.target_user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot remove the primary target from a case",
        )

    await session.delete(link)
    await session.flush()
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def add_case_note(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    body: ModerationCaseNoteCreateModel,
    author_user_id: int,
) -> ModerationCaseNoteReadModel:
    await get_case_or_404(server_id, case_id, session)
    author = await build_actor(session, server_id, author_user_id, require_membership=True)

    note = ModerationCaseNote(
        case_id=case_id,
        author_user_id=author_user_id,
        note=body.note,
        is_internal=body.is_internal,
    )
    session.add(note)
    await session.flush()
    await session.refresh(note)
    return ModerationCaseNoteReadModel(
        id=str(note.id),
        case_id=str(note.case_id),
        note=note.note,
        is_internal=note.is_internal,
        created_at=note.created_at,
        author=author,
    )


async def add_case_evidence(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    body: ModerationCaseEvidenceCreateModel,
    added_by_user_id: int,
) -> ModerationCaseEvidenceReadModel:
    await get_case_or_404(server_id, case_id, session)
    if not body.url and not body.text and not body.attachment_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of url, text, or attachment_key must be provided",
        )

    added_by = await build_actor(session, server_id, added_by_user_id, require_membership=True)
    evidence = ModerationCaseEvidence(
        case_id=case_id,
        added_by_user_id=added_by_user_id,
        evidence_type=body.evidence_type,
        url=body.url,
        text=body.text,
        attachment_key=body.attachment_key,
    )
    session.add(evidence)
    await session.flush()
    await session.refresh(evidence)
    return ModerationCaseEvidenceReadModel(
        id=str(evidence.id),
        case_id=str(evidence.case_id),
        evidence_type=evidence.evidence_type,
        url=evidence.url,
        text=evidence.text,
        attachment_key=evidence.attachment_key,
        created_at=evidence.created_at,
        added_by=added_by,
    )


async def link_action_to_case(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    moderation_action_id: str,
    linked_by_user_id: int,
) -> ModerationCaseReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    await build_actor(session, server_id, linked_by_user_id, require_membership=True)

    try:
        action_id = UUID(moderation_action_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid moderation_action_id")

    action = await session.get(ModerationAction, action_id)
    if not action or action.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    if action.case_id is None:
        action.case_id = case_id
        session.add(action)
    elif action.case_id != case_id:
        # Keep existing canonical link and persist this one as secondary.
        pass

    existing_link = (
        await session.exec(
            select(ModerationCaseActionLink).where(
                ModerationCaseActionLink.case_id == case_id,
                ModerationCaseActionLink.moderation_action_id == action_id,
            )
        )
    ).first()
    if not existing_link:
        session.add(
            ModerationCaseActionLink(
                case_id=case_id,
                moderation_action_id=action_id,
                linked_by_user_id=linked_by_user_id,
            )
        )
        await session.flush()

    action_rule_ids = (
        await session.exec(
            select(ModerationActionRuleCitation.rule_id).where(
                ModerationActionRuleCitation.action_id == action_id,
                ModerationActionRuleCitation.rule_id.is_not(None),
            )
        )
    ).all()
    parsed_action_rule_ids = [rule_id for rule_id in action_rule_ids if rule_id is not None]
    if not parsed_action_rule_ids and action.rule_id is not None:
        parsed_action_rule_ids = [action.rule_id]
    if parsed_action_rule_ids:
        resolved_rules = await _resolve_case_rules(
            session=session,
            server_id=server_id,
            rule_ids=list(dict.fromkeys(parsed_action_rule_ids)),
        )
        await _upsert_case_rule_citations(
            session=session,
            moderation_case=moderation_case,
            rules=resolved_rules,
            cited_at=naive_utcnow(),
        )

    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def upsert_case_rules(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    body: ModerationCaseRulesUpsertModel,
) -> ModerationCaseReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    parsed_rule_ids = _parse_rule_ids(body.rule_ids or [])
    rules = await _resolve_case_rules(session=session, server_id=server_id, rule_ids=parsed_rule_ids)
    await _upsert_case_rule_citations(
        session=session,
        moderation_case=moderation_case,
        rules=rules,
        cited_at=naive_utcnow(),
    )
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def remove_case_rule(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    rule_id: UUID,
) -> ModerationCaseReadModel:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    citation = (
        await session.exec(
            select(ModerationCaseRuleCitation).where(
                ModerationCaseRuleCitation.case_id == case_id,
                ModerationCaseRuleCitation.rule_id == rule_id,
            )
        )
    ).first()
    if not citation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case rule citation not found")
    await session.delete(citation)
    await session.flush()
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def create_action_from_case(
    session: AsyncSession,
    server_id: int,
    case_id: UUID,
    body: ModerationCaseActionCreateFromCaseModel,
    actor_user_id: int,
) -> ModerationActionRead:
    moderation_case = await get_case_or_404(server_id, case_id, session)
    await build_actor(session, server_id, actor_user_id, require_membership=True)

    target_user_id = int(body.target_user_id) if body.target_user_id and body.target_user_id.isdigit() else moderation_case.target_user_id
    case_users = (
        await session.exec(
            select(ModerationCaseUser.user_id).where(ModerationCaseUser.case_id == case_id)
        )
    ).all()
    allowed_targets = {moderation_case.target_user_id, *[int(item) for item in case_users]}
    if target_user_id not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target_user_id must belong to case users",
        )

    target_global_user = await session.get(GlobalUser, target_user_id)
    target_membership = (
        await session.exec(
            select(User).where(
                User.server_id == server_id,
                User.user_id == target_user_id,
            )
        )
    ).first()
    if not target_global_user or not target_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found")

    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    case_rule_ids = await _list_case_rule_ids(session=session, case_id=case_id)
    resolved_rule_ids = body.rule_ids if body.rule_ids is not None else case_rule_ids

    action_payload = ModerationActionCreate(
        action_type=body.action_type,
        moderator_user_id=actor_user_id,
        reason=body.reason or moderation_case.title,
        rule_ids=resolved_rule_ids,
        expires_at=body.expires_at,
        target_user_id=target_user_id,
        target_user_name=target_global_user.username or str(target_user_id),
        target_user_joined_at=target_global_user.joined_discord or moderation_case.created_at,
        target_user_server_nickname=target_membership.server_nickname,
        server_id=server_id,
        server_name=server.server_name or str(server_id),
    )
    created_action = await create_action(
        session=session,
        action=action_payload,
        moderator_user_id=actor_user_id,
        case_id=case_id,
    )

    session.add(
        ModerationCaseNote(
            case_id=case_id,
            author_user_id=None,
            note=f"System linked action {created_action.id} to this case.",
            is_internal=True,
        )
    )
    await session.flush()

    return to_moderation_history([created_action])[0]


def store_evidence_blob(
    key: str,
    payload: bytes,
    content_type: str | None,
    root: Path = EVIDENCE_UPLOAD_ROOT,
) -> dict:
    if "/" in key or "\\" in key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload key")
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty payload")

    root.mkdir(parents=True, exist_ok=True)
    file_path = root / key
    file_path.write_bytes(payload)

    metadata_path = root / f"{key}.meta"
    metadata_path.write_text((content_type or "application/octet-stream"), encoding="utf-8")
    return {"key": key}
