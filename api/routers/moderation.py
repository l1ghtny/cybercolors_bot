from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_cases import (
    DeletedMessageCreateModel,
    DeletedMessageLinkModel,
    DeletedMessageReadModel,
    ModerationActorModel,
    ModerationCaseActionLinkCreateModel,
    ModerationCaseCreateModel,
    ModerationCaseDetailsModel,
    ModerationCaseEvidenceCreateModel,
    ModerationCaseEvidenceReadModel,
    ModerationCaseUserAddModel,
    ModerationCaseUserReadModel,
    ModerationEvidenceUploadUrlRequest,
    ModerationEvidenceUploadUrlResponse,
    ModerationCaseNoteCreateModel,
    ModerationCaseNoteReadModel,
    ModerationCaseReadModel,
    ModerationCaseStatusUpdateModel,
)
from api.models.user_profiles import (
    NicknameLogModel,
    NicknameRecordModel,
    UserActivitySummaryModel,
    UserModerationActionSummaryModel,
    UserModerationCaseSummaryModel,
    UserProfileCardModel,
)
from api.services.discord_guilds import fetch_guild_channels
from api.services.moderation_queries import (
    query_deleted_messages,
    query_deleted_messages_for_action,
    query_moderation_actions,
)
from src.db.database import get_session
from src.db.models import (
    ActionType,
    CaseStatus,
    CaseUserRole,
    DeletedMessage,
    GlobalUser,
    ModerationAction,
    ModerationActionDeletedMessageLink,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseEvidence,
    ModerationCaseNote,
    ModerationCaseUser,
    PastNickname,
    Server,
    User,
    UserActivity,
)
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

moderation = APIRouter(prefix="/moderation", tags=["moderation"])
EVIDENCE_UPLOAD_ROOT = Path("logs") / "moderation_evidence"


class ModerationActionCreate(BaseModel):
    action_type: ActionType
    moderator_user_id: int
    reason: str
    expires_at: datetime | None = None
    target_user_id: int
    target_user_name: str
    target_user_joined_at: datetime
    target_user_server_nickname: str | None
    server_id: int
    server_name: str


class ModerationActionRead(BaseModel):
    id: str
    action_type: ActionType
    server_id: str
    target_user_id: str
    target_user_username: str
    moderator_user_id: str
    moderator_username: str
    reason: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    is_active: bool


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_upload_key(server_id: int, case_id: UUID, filename: str) -> str:
    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()[:10]
    return f"{server_id}_{case_id}_{uuid4().hex}{ext}"


async def _get_or_create_server_record(server_id: int, session: AsyncSession) -> Server:
    server = await session.get(Server, server_id)
    if server:
        return server
    server = Server(server_id=server_id, server_name=str(server_id))
    session.add(server)
    await session.flush()
    return server


async def _get_or_create_user_membership(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    username: str | None = None,
    server_nickname: str | None = None,
) -> tuple[GlobalUser, User]:
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        global_user = GlobalUser(discord_id=user_id, username=username)
        session.add(global_user)
        await session.flush()
    elif username and global_user.username != username:
        global_user.username = username
        session.add(global_user)

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    if not membership:
        membership = User(
            user_id=user_id,
            server_id=server_id,
            server_nickname=server_nickname,
            is_member=True,
        )
        session.add(membership)
        await session.flush()
    else:
        if server_nickname:
            membership.server_nickname = server_nickname
        membership.is_member = True
        session.add(membership)

    return global_user, membership


def _to_nickname_record(item: PastNickname) -> NicknameRecordModel:
    return NicknameRecordModel(
        id=str(item.id),
        user_id=str(item.user_id),
        server_id=str(item.server_id) if item.server_id is not None else None,
        server_name=item.server_name,
        nickname=item.discord_name,
        recorded_at=item.recorded_at,
    )


async def _get_nickname_history(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int,
) -> list[PastNickname]:
    server = await session.get(Server, server_id)
    base = select(PastNickname).where(PastNickname.user_id == user_id)
    if server and server.server_name:
        base = base.where(
            or_(
                PastNickname.server_id == server_id,
                (PastNickname.server_id.is_(None) & (PastNickname.server_name == server.server_name)),
            )
        )
    else:
        base = base.where(PastNickname.server_id == server_id)

    rows = (
        await session.exec(
            base.order_by(PastNickname.recorded_at.desc()).limit(limit)
        )
    ).all()

    if rows:
        return rows

    # Fallback for legacy records that may lack server linkage.
    return (
        await session.exec(
            select(PastNickname)
            .where(PastNickname.user_id == user_id)
            .order_by(PastNickname.recorded_at.desc())
            .limit(limit)
        )
    ).all()


async def _get_case_or_404(server_id: int, case_id: UUID, session: AsyncSession) -> ModerationCase:
    moderation_case = await session.get(ModerationCase, case_id)
    if not moderation_case or moderation_case.server_id != server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation case not found")
    return moderation_case


async def _build_actor(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    require_membership: bool = False,
) -> ModerationActorModel:
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found")

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    if require_membership and not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} is not a member of server {server_id}",
        )

    display_name = (
        membership.server_nickname
        if membership and membership.server_nickname
        else (global_user.username or str(user_id))
    )
    return ModerationActorModel(
        user_id=str(user_id),
        username=global_user.username,
        server_nickname=membership.server_nickname if membership else None,
        display_name=display_name,
        avatar_hash=global_user.avatar_hash,
    )


async def _build_optional_actor(
    session: AsyncSession,
    server_id: int,
    user_id: int | None,
) -> ModerationActorModel | None:
    if user_id is None:
        return None
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        return ModerationActorModel(
            user_id=str(user_id),
            username=None,
            server_nickname=None,
            display_name=str(user_id),
            avatar_hash=None,
        )
    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    return ModerationActorModel(
        user_id=str(user_id),
        username=global_user.username,
        server_nickname=membership.server_nickname if membership else None,
        display_name=(
            membership.server_nickname
            if membership and membership.server_nickname
            else (global_user.username or str(user_id))
        ),
        avatar_hash=global_user.avatar_hash,
    )


async def _to_case_read(moderation_case: ModerationCase, session: AsyncSession) -> ModerationCaseReadModel:
    target_user = await _build_actor(session, moderation_case.server_id, moderation_case.target_user_id)
    opened_by = await _build_actor(session, moderation_case.server_id, moderation_case.opened_by_user_id)
    closed_by = await _build_optional_actor(session, moderation_case.server_id, moderation_case.closed_by_user_id)

    case_user_links = (
        await session.exec(
            select(ModerationCaseUser)
            .where(ModerationCaseUser.case_id == moderation_case.id)
            .order_by(ModerationCaseUser.added_at.asc())
        )
    ).all()
    case_users: list[ModerationCaseUserReadModel] = []
    for link in case_user_links:
        case_users.append(
            ModerationCaseUserReadModel(
                id=str(link.id),
                role=link.role,
                added_at=link.added_at,
                added_by=await _build_actor(session, moderation_case.server_id, link.added_by_user_id),
                user=await _build_actor(session, moderation_case.server_id, link.user_id),
            )
        )

    linked_actions = (
        await session.exec(
            select(ModerationCaseActionLink.moderation_action_id).where(
                ModerationCaseActionLink.case_id == moderation_case.id
            )
        )
    ).all()

    return ModerationCaseReadModel(
        id=str(moderation_case.id),
        server_id=str(moderation_case.server_id),
        title=moderation_case.title,
        summary=moderation_case.summary,
        status=moderation_case.status,
        created_at=moderation_case.created_at,
        closed_at=moderation_case.closed_at,
        target_user=target_user,
        opened_by=opened_by,
        closed_by=closed_by,
        users=case_users,
        linked_action_ids=[str(action_id) for action_id in linked_actions],
    )


async def _to_deleted_message_read(
    deleted_message: DeletedMessage,
    session: AsyncSession,
    channel_name: str | None = None,
) -> DeletedMessageReadModel:
    author = await _build_optional_actor(session, deleted_message.server_id, deleted_message.author_user_id)
    deleted_by = await _build_optional_actor(session, deleted_message.server_id, deleted_message.deleted_by_user_id)

    return DeletedMessageReadModel(
        id=str(deleted_message.id),
        server_id=str(deleted_message.server_id),
        message_id=str(deleted_message.message_id),
        channel_id=str(deleted_message.channel_id),
        channel_name=channel_name,
        content=deleted_message.content,
        attachments_json=deleted_message.attachments_json,
        deleted_at=deleted_message.deleted_at,
        author=author,
        deleted_by=deleted_by,
    )


@moderation.post("/create_action", response_model=ModerationAction)
async def create_moderation_action(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session),
):
    mock_user = type(
        "MockUser",
        (),
        {
            "id": action.target_user_id,
            "name": action.target_user_name,
            "joined_at": action.target_user_joined_at,
            "nick": action.target_user_server_nickname,
        },
    )()
    mock_server = type("MockServer", (), {"id": action.server_id, "name": action.server_name})()

    await check_if_server_exists(mock_server, session)
    await check_if_user_exists(mock_user, mock_server, session)

    db_action = ModerationAction.model_validate(action)
    session.add(db_action)
    await session.flush()
    await session.refresh(db_action)
    return db_action


@moderation.get("/history/{server_id}/get_user_history", response_model=List[ModerationActionRead])
async def get_user_history(
    server_id: int,
    search: str = Query(..., description="The ID or username of the user to search for."),
    session: AsyncSession = Depends(get_session),
):
    target_user_id: int

    if search.isdigit():
        target_user_id = int(search)
    else:
        user_result = await session.exec(select(GlobalUser).where(GlobalUser.username == search))
        user = user_result.one_or_none()
        if not user:
            return []
        target_user_id = user.discord_id

    statement = (
        select(ModerationAction)
        .where(
            ModerationAction.server_id == server_id,
            ModerationAction.target_user_id == target_user_id,
        )
        .options(selectinload(ModerationAction.global_user_moderator))
        .order_by(ModerationAction.created_at)
    )

    result = await session.exec(statement)
    actions = result.all()
    return await _return_moderation_history(actions)


@moderation.get("/history/{server_id}/", response_model=List[ModerationActionRead])
async def get_server_moderation_history(
    server_id: int,
    target_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    target_user_id_int = int(target_user_id) if target_user_id else None
    result = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id_int,
        limit=limit,
    )
    return await _return_moderation_history(result)


@moderation.post("/cases/{server_id}", response_model=ModerationCaseReadModel, status_code=status.HTTP_201_CREATED)
async def create_moderation_case(
    server_id: int,
    body: ModerationCaseCreateModel,
    session: AsyncSession = Depends(get_session),
):
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    target_user_id = int(body.target_user_id)
    opened_by_user_id = int(body.opened_by_user_id)
    await _build_actor(session, server_id, target_user_id, require_membership=True)
    await _build_actor(session, server_id, opened_by_user_id, require_membership=True)

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
    return await _to_case_read(moderation_case, session)


@moderation.get("/cases/{server_id}", response_model=List[ModerationCaseReadModel])
async def list_moderation_cases(
    server_id: int,
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    target_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    session: AsyncSession = Depends(get_session),
):
    statement = select(ModerationCase).where(ModerationCase.server_id == server_id)
    if status_filter:
        statement = statement.where(ModerationCase.status == status_filter)
    if target_user_id:
        statement = statement.where(ModerationCase.target_user_id == int(target_user_id))

    statement = statement.order_by(ModerationCase.created_at.desc())
    cases = (await session.exec(statement)).all()
    return [await _to_case_read(case, session) for case in cases]


@moderation.get("/cases/{server_id}/{case_id}", response_model=ModerationCaseDetailsModel)
async def get_moderation_case_details(
    server_id: int,
    case_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    moderation_case = await _get_case_or_404(server_id, case_id, session)
    case_data = await _to_case_read(moderation_case, session)

    notes = (
        await session.exec(
            select(ModerationCaseNote)
            .where(ModerationCaseNote.case_id == case_id)
            .order_by(ModerationCaseNote.created_at.desc())
        )
    ).all()
    note_rows: list[ModerationCaseNoteReadModel] = []
    for note in notes:
        author = await _build_actor(session, server_id, note.author_user_id)
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
        added_by = await _build_actor(session, server_id, evidence.added_by_user_id)
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


@moderation.patch("/cases/{server_id}/{case_id}/status", response_model=ModerationCaseReadModel)
async def update_moderation_case_status(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseStatusUpdateModel,
    session: AsyncSession = Depends(get_session),
):
    moderation_case = await _get_case_or_404(server_id, case_id, session)

    if body.status == CaseStatus.OPEN:
        moderation_case.status = CaseStatus.OPEN
        moderation_case.closed_at = None
        moderation_case.closed_by_user_id = None
    else:
        if not body.closed_by_user_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="closed_by_user_id is required when closing or archiving a case",
            )
        closed_by_user_id = int(body.closed_by_user_id)
        await _build_actor(session, server_id, closed_by_user_id, require_membership=True)
        moderation_case.status = body.status
        moderation_case.closed_at = _naive_utcnow()
        moderation_case.closed_by_user_id = closed_by_user_id

    session.add(moderation_case)
    await session.flush()
    await session.refresh(moderation_case)
    return await _to_case_read(moderation_case, session)


@moderation.get("/cases/{server_id}/{case_id}/users", response_model=list[ModerationCaseUserReadModel])
async def get_case_users(
    server_id: int,
    case_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    moderation_case = await _get_case_or_404(server_id, case_id, session)
    case_data = await _to_case_read(moderation_case, session)
    return case_data.users


@moderation.post("/cases/{server_id}/{case_id}/users", response_model=ModerationCaseReadModel)
async def add_user_to_case(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseUserAddModel,
    session: AsyncSession = Depends(get_session),
):
    moderation_case = await _get_case_or_404(server_id, case_id, session)
    user_id = int(body.user_id)
    added_by_user_id = int(body.added_by_user_id)

    await _build_actor(session, server_id, user_id)
    await _build_actor(session, server_id, added_by_user_id, require_membership=True)

    existing_link = (
        await session.exec(
            select(ModerationCaseUser).where(
                ModerationCaseUser.case_id == case_id,
                ModerationCaseUser.user_id == user_id,
            )
        )
    ).first()

    if body.role == CaseUserRole.PRIMARY_TARGET:
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
        existing_link.role = body.role
        session.add(existing_link)
    else:
        session.add(
            ModerationCaseUser(
                case_id=case_id,
                user_id=user_id,
                role=body.role,
                added_by_user_id=added_by_user_id,
            )
        )

    await session.flush()
    await session.refresh(moderation_case)
    return await _to_case_read(moderation_case, session)


@moderation.delete("/cases/{server_id}/{case_id}/users/{user_id}", response_model=ModerationCaseReadModel)
async def remove_user_from_case(
    server_id: int,
    case_id: UUID,
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    moderation_case = await _get_case_or_404(server_id, case_id, session)
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
    return await _to_case_read(moderation_case, session)


@moderation.post(
    "/cases/{server_id}/{case_id}/notes",
    response_model=ModerationCaseNoteReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_moderation_case_note(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseNoteCreateModel,
    session: AsyncSession = Depends(get_session),
):
    await _get_case_or_404(server_id, case_id, session)
    author_user_id = int(body.author_user_id)
    author = await _build_actor(session, server_id, author_user_id, require_membership=True)

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


@moderation.post(
    "/cases/{server_id}/{case_id}/evidence",
    response_model=ModerationCaseEvidenceReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_moderation_case_evidence(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseEvidenceCreateModel,
    session: AsyncSession = Depends(get_session),
):
    await _get_case_or_404(server_id, case_id, session)
    if not body.url and not body.text and not body.attachment_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of url, text, or attachment_key must be provided",
        )

    added_by_user_id = int(body.added_by_user_id)
    added_by = await _build_actor(session, server_id, added_by_user_id, require_membership=True)

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


@moderation.post(
    "/cases/{server_id}/{case_id}/evidence/upload-url",
    response_model=ModerationEvidenceUploadUrlResponse,
)
async def create_evidence_upload_url(
    server_id: int,
    case_id: UUID,
    body: ModerationEvidenceUploadUrlRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    await _get_case_or_404(server_id, case_id, session)
    key = _safe_upload_key(server_id, case_id, body.filename)
    upload_url = str(request.base_url) + f"moderation/evidence/upload/{key}"
    return ModerationEvidenceUploadUrlResponse(upload_url=upload_url, key=key, method="PUT")


@moderation.put("/evidence/upload/{key}", status_code=status.HTTP_201_CREATED)
async def upload_evidence_blob(
    key: str,
    payload: bytes = Body(...),
    content_type: str | None = Header(default=None, alias="Content-Type"),
):
    if "/" in key or "\\" in key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload key")
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty payload")

    EVIDENCE_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    file_path = EVIDENCE_UPLOAD_ROOT / key
    file_path.write_bytes(payload)

    metadata_path = EVIDENCE_UPLOAD_ROOT / f"{key}.meta"
    metadata_path.write_text((content_type or "application/octet-stream"), encoding="utf-8")
    return {"key": key}


@moderation.post("/cases/{server_id}/{case_id}/actions", response_model=ModerationCaseReadModel)
async def link_action_to_moderation_case(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseActionLinkCreateModel,
    session: AsyncSession = Depends(get_session),
):
    moderation_case = await _get_case_or_404(server_id, case_id, session)
    linked_by_user_id = int(body.linked_by_user_id)
    await _build_actor(session, server_id, linked_by_user_id, require_membership=True)

    try:
        action_id = UUID(body.moderation_action_id)
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
        link = ModerationCaseActionLink(
            case_id=case_id,
            moderation_action_id=action_id,
            linked_by_user_id=linked_by_user_id,
        )
        session.add(link)
        await session.flush()

    await session.refresh(moderation_case)
    return await _to_case_read(moderation_case, session)


@moderation.post(
    "/actions/{action_id}/deleted-messages",
    response_model=DeletedMessageReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_deleted_message_for_action(
    action_id: UUID,
    body: DeletedMessageCreateModel,
    session: AsyncSession = Depends(get_session),
):
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    server_id = action.server_id
    linked_by_user_id = int(body.linked_by_user_id)
    await _build_actor(session, server_id, linked_by_user_id, require_membership=True)

    author_user_id = int(body.author_user_id) if body.author_user_id else None
    deleted_by_user_id = int(body.deleted_by_user_id) if body.deleted_by_user_id else None
    if author_user_id:
        await _build_actor(session, server_id, author_user_id)
    if deleted_by_user_id:
        await _build_actor(session, server_id, deleted_by_user_id)

    deleted_message = DeletedMessage(
        server_id=server_id,
        message_id=int(body.message_id),
        channel_id=int(body.channel_id),
        author_user_id=author_user_id,
        content=body.content,
        attachments_json=body.attachments_json,
        deleted_at=body.deleted_at or _naive_utcnow(),
        deleted_by_user_id=deleted_by_user_id,
    )
    session.add(deleted_message)
    await session.flush()
    await session.refresh(deleted_message)

    link = ModerationActionDeletedMessageLink(
        moderation_action_id=action_id,
        deleted_message_id=deleted_message.id,
        linked_by_user_id=linked_by_user_id,
    )
    session.add(link)
    await session.flush()

    return await _to_deleted_message_read(deleted_message, session)


@moderation.post(
    "/actions/{action_id}/deleted-messages/{deleted_message_id}/link",
    response_model=DeletedMessageReadModel,
)
async def link_existing_deleted_message_to_action(
    action_id: UUID,
    deleted_message_id: UUID,
    body: DeletedMessageLinkModel,
    session: AsyncSession = Depends(get_session),
):
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_message = await session.get(DeletedMessage, deleted_message_id)
    if not deleted_message or deleted_message.server_id != action.server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted message not found")

    linked_by_user_id = int(body.linked_by_user_id)
    await _build_actor(session, action.server_id, linked_by_user_id, require_membership=True)

    existing_link = (
        await session.exec(
            select(ModerationActionDeletedMessageLink).where(
                ModerationActionDeletedMessageLink.moderation_action_id == action_id,
                ModerationActionDeletedMessageLink.deleted_message_id == deleted_message_id,
            )
        )
    ).first()
    if not existing_link:
        link = ModerationActionDeletedMessageLink(
            moderation_action_id=action_id,
            deleted_message_id=deleted_message_id,
            linked_by_user_id=linked_by_user_id,
        )
        session.add(link)
        await session.flush()

    channel_names: dict[int, str] = {}
    try:
        channels = await fetch_guild_channels(action.server_id)
        channel_names = {int(ch["id"]): ch.get("name", "") for ch in channels}
    except Exception:
        channel_names = {}

    return await _to_deleted_message_read(
        deleted_message,
        session,
        channel_name=channel_names.get(deleted_message.channel_id),
    )


@moderation.get("/actions/{action_id}/deleted-messages", response_model=list[DeletedMessageReadModel])
async def get_deleted_messages_for_action(action_id: UUID, session: AsyncSession = Depends(get_session)):
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_messages = await query_deleted_messages_for_action(session=session, action_id=action_id)
    channel_names: dict[int, str] = {}
    try:
        channels = await fetch_guild_channels(action.server_id)
        channel_names = {int(ch["id"]): ch.get("name", "") for ch in channels}
    except Exception:
        channel_names = {}

    return [
        await _to_deleted_message_read(
            item,
            session,
            channel_name=channel_names.get(item.channel_id),
        )
        for item in deleted_messages
    ]


@moderation.get("/deleted-messages/{server_id}", response_model=list[DeletedMessageReadModel])
async def browse_deleted_messages(
    server_id: int,
    author_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    channel_id: str | None = Query(default=None, pattern=r"^\d+$"),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    messages = await query_deleted_messages(
        session=session,
        server_id=server_id,
        author_user_id=int(author_user_id) if author_user_id else None,
        channel_id=int(channel_id) if channel_id else None,
        since=since,
        limit=limit,
    )

    channel_names: dict[int, str] = {}
    try:
        channels = await fetch_guild_channels(server_id)
        channel_names = {int(ch["id"]): ch.get("name", "") for ch in channels}
    except Exception:
        channel_names = {}

    return [
        await _to_deleted_message_read(
            item,
            session,
            channel_name=channel_names.get(item.channel_id),
        )
        for item in messages
    ]


@moderation.post(
    "/users/{server_id}/{user_id}/nicknames",
    response_model=NicknameRecordModel,
    status_code=status.HTTP_201_CREATED,
)
async def log_user_nickname(
    server_id: int,
    user_id: int,
    body: NicknameLogModel,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_create_server_record(server_id, session)
    _, membership = await _get_or_create_user_membership(
        session=session,
        server_id=server_id,
        user_id=user_id,
        server_nickname=body.nickname,
    )

    latest = (
        await session.exec(
            select(PastNickname)
            .where(PastNickname.user_id == user_id, PastNickname.server_id == server_id)
            .order_by(PastNickname.recorded_at.desc())
            .limit(1)
        )
    ).first()
    if latest and latest.discord_name == body.nickname:
        return _to_nickname_record(latest)

    nickname_record = PastNickname(
        user_id=user_id,
        discord_name=body.nickname,
        server_name=body.server_name or server.server_name or str(server_id),
        server_id=server_id,
        recorded_at=body.recorded_at or _naive_utcnow(),
    )
    session.add(nickname_record)

    if membership.server_nickname != body.nickname:
        membership.server_nickname = body.nickname
        session.add(membership)

    await session.flush()
    await session.refresh(nickname_record)
    return _to_nickname_record(nickname_record)


@moderation.get("/users/{server_id}/{user_id}/nicknames", response_model=list[NicknameRecordModel])
async def get_user_nickname_history(
    server_id: int,
    user_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    history = await _get_nickname_history(session, server_id, user_id, limit)
    return [_to_nickname_record(item) for item in history]


@moderation.get("/users/{server_id}/{user_id}/profile", response_model=UserProfileCardModel)
async def get_user_profile_card(
    server_id: int,
    user_id: int,
    history_limit: int = Query(default=20, ge=1, le=100),
    actions_limit: int = Query(default=10, ge=1, le=50),
    cases_limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    display_name = (
        membership.server_nickname
        if membership and membership.server_nickname
        else (global_user.username or str(user_id))
    )

    activity = await session.get(UserActivity, (user_id, server_id))
    activity_payload = (
        UserActivitySummaryModel(
            user_id=str(activity.user_id),
            server_id=str(activity.server_id),
            channel_id=str(activity.channel_id),
            message_count=activity.message_count,
            last_message_at=activity.last_message_at,
        )
        if activity
        else None
    )

    nickname_history = await _get_nickname_history(session, server_id, user_id, history_limit)

    actions = (
        await session.exec(
            select(ModerationAction)
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == user_id,
            )
            .options(selectinload(ModerationAction.global_user_moderator))
            .order_by(ModerationAction.created_at.desc())
            .limit(actions_limit)
        )
    ).all()
    actions_count = (
        await session.exec(
            select(func.count())
            .select_from(ModerationAction)
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == user_id,
            )
        )
    ).one()

    cases = (
        await session.exec(
            select(ModerationCase)
            .where(
                ModerationCase.server_id == server_id,
                ModerationCase.target_user_id == user_id,
            )
            .order_by(ModerationCase.created_at.desc())
            .limit(cases_limit)
        )
    ).all()
    open_cases_count = (
        await session.exec(
            select(func.count())
            .select_from(ModerationCase)
            .where(
                ModerationCase.server_id == server_id,
                ModerationCase.target_user_id == user_id,
                ModerationCase.status == CaseStatus.OPEN,
            )
        )
    ).one()

    return UserProfileCardModel(
        user_id=str(user_id),
        username=global_user.username,
        server_nickname=membership.server_nickname if membership else None,
        display_name=display_name,
        avatar_hash=global_user.avatar_hash,
        joined_discord=global_user.joined_discord,
        is_member=membership.is_member if membership else False,
        flagged_absent_at=membership.flagged_absent_at if membership else None,
        activity=activity_payload,
        nickname_history=[_to_nickname_record(item) for item in nickname_history],
        moderation_actions_count=int(actions_count),
        open_cases_count=int(open_cases_count),
        recent_actions=[
            UserModerationActionSummaryModel(
                id=str(action.id),
                action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type),
                reason=action.reason,
                created_at=action.created_at,
                moderator_user_id=str(action.moderator_user_id),
                moderator_username=(
                    action.global_user_moderator.username
                    if action.global_user_moderator
                    else None
                ),
            )
            for action in actions
        ],
        recent_cases=[
            UserModerationCaseSummaryModel(
                id=str(case.id),
                title=case.title,
                status=case.status,
                created_at=case.created_at,
            )
            for case in cases
        ],
    )


@moderation.get("/users/{server_id}/{user_id}/actions", response_model=List[ModerationActionRead])
async def get_actions_for_user(
    server_id: int,
    user_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    statement = (
        select(ModerationAction)
        .where(
            ModerationAction.server_id == server_id,
            ModerationAction.target_user_id == user_id,
        )
        .options(
            selectinload(ModerationAction.global_user_moderator),
            selectinload(ModerationAction.global_user_target),
        )
        .order_by(ModerationAction.created_at.desc())
        .limit(limit)
    )
    actions = (await session.exec(statement)).all()
    return await _return_moderation_history(actions)


@moderation.get("/users/{server_id}/{user_id}/cases", response_model=List[ModerationCaseReadModel])
async def get_cases_for_user(
    server_id: int,
    user_id: int,
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    statement = select(ModerationCase).where(
        ModerationCase.server_id == server_id,
        ModerationCase.target_user_id == user_id,
    )
    if status_filter:
        statement = statement.where(ModerationCase.status == status_filter)

    statement = statement.order_by(ModerationCase.created_at.desc()).limit(limit)
    cases = (await session.exec(statement)).all()
    return [await _to_case_read(case, session) for case in cases]


async def _return_moderation_history(result):
    return [
        ModerationActionRead(
            id=str(action.id),
            action_type=action.action_type,
            server_id=str(action.server_id),
            target_user_id=str(action.target_user_id),
            target_user_username=str(action.global_user_target.username),
            moderator_user_id=str(action.moderator_user_id),
            moderator_username=str(action.global_user_moderator.username),
            reason=action.reason,
            created_at=action.created_at,
            expires_at=action.expires_at,
            is_active=action.is_active,
        )
        for action in result
    ]
