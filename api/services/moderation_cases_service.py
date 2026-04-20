from datetime import datetime
from pathlib import Path
from typing import List
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_cases import (
    ModerationCaseCreateModel,
    ModerationCaseDetailsModel,
    ModerationCaseEvidenceCreateModel,
    ModerationCaseEvidenceReadModel,
    ModerationCaseNoteCreateModel,
    ModerationCaseNoteReadModel,
    ModerationCaseReadModel,
    ModerationCaseStatusUpdateModel,
    ModerationCaseUserReadModel,
)
from api.services.moderation_core import build_actor, get_case_or_404, naive_utcnow, to_case_read
from src.db.models import (
    CaseStatus,
    CaseUserRole,
    ModerationAction,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseEvidence,
    ModerationCaseNote,
    ModerationCaseUser,
    Server,
)

EVIDENCE_UPLOAD_ROOT = Path("logs") / "moderation_evidence"


def safe_upload_key(server_id: int, case_id: UUID, filename: str) -> str:
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()[:10]
    return f"{server_id}_{case_id}_{uuid4().hex}{ext}"


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
    await session.flush()
    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


async def list_cases(
    session: AsyncSession,
    server_id: int,
    status_filter: CaseStatus | None = None,
    target_user_id: str | None = None,
    user_id: str | None = None,
) -> list[ModerationCaseReadModel]:
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
    cases = (await session.exec(statement)).all()
    return [await to_case_read(item, session) for item in cases]


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
        author = await build_actor(session, server_id, note.author_user_id)
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

    await session.refresh(moderation_case)
    return await to_case_read(moderation_case, session)


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
