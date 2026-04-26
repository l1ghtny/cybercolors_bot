from typing import List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_optional_current_discord_user_id, resolve_actor_user_id
from api.dependencies.server_access import require_server_dashboard_access
from api.models.moderation_actions import ModerationActionRead
from api.models.moderation_cases import (
    ModerationCaseActionCreateFromCaseModel,
    ModerationCaseActionLinkCreateModel,
    ModerationCaseCreateModel,
    ModerationCaseDetailsModel,
    ModerationCaseEvidenceCreateModel,
    ModerationCaseEvidenceReadModel,
    ModerationCaseNoteCreateModel,
    ModerationCaseNoteReadModel,
    ModerationCaseReadModel,
    ModerationCaseRulesUpsertModel,
    ModerationCaseStatusUpdateModel,
    ModerationCaseUserAddModel,
    ModerationCaseUserReadModel,
    ModerationEvidenceUploadUrlRequest,
    ModerationEvidenceUploadResult,
    ModerationEvidenceUploadUrlResponse,
)
from api.services.moderation_cases_service import (
    add_case_evidence as add_case_evidence_service,
    add_case_note as add_case_note_service,
    add_user_to_case as add_user_to_case_service,
    create_action_from_case as create_action_from_case_service,
    create_case as create_case_service,
    get_case_details as get_case_details_service,
    link_action_to_case as link_action_to_case_service,
    list_case_users as list_case_users_service,
    list_cases as list_cases_service,
    remove_user_from_case as remove_user_from_case_service,
    remove_case_rule as remove_case_rule_service,
    safe_upload_key,
    store_evidence_blob,
    upsert_case_rules as upsert_case_rules_service,
    update_case_status as update_case_status_service,
)
from api.services.moderation_core import get_case_or_404
from src.db.database import get_session
from src.db.models import CaseStatus

moderation_cases_router = APIRouter()


@moderation_cases_router.post(
    "/cases/{server_id}",
    response_model=ModerationCaseReadModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def create_moderation_case(
    server_id: int,
    body: ModerationCaseCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    opened_by_user_id = resolve_actor_user_id(body.opened_by_user_id, current_user_id)
    return await create_case_service(
        session=session,
        server_id=server_id,
        body=body,
        opened_by_user_id=opened_by_user_id,
    )


@moderation_cases_router.get(
    "/cases/{server_id}",
    response_model=List[ModerationCaseReadModel],
    dependencies=[Depends(require_server_dashboard_access)],
)
async def list_moderation_cases(
    server_id: int,
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    target_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    session: AsyncSession = Depends(get_session),
):
    return await list_cases_service(
        session=session,
        server_id=server_id,
        status_filter=status_filter,
        target_user_id=target_user_id,
        user_id=user_id,
    )


@moderation_cases_router.get(
    "/cases/{server_id}/{case_id}",
    response_model=ModerationCaseDetailsModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_moderation_case_details(
    server_id: int,
    case_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await get_case_details_service(session=session, server_id=server_id, case_id=case_id)


@moderation_cases_router.patch(
    "/cases/{server_id}/{case_id}/status",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def update_moderation_case_status(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseStatusUpdateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    closed_by_user_id = None
    if body.status != CaseStatus.OPEN:
        closed_by_user_id = resolve_actor_user_id(body.closed_by_user_id, current_user_id)
    return await update_case_status_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        body=body,
        closed_by_user_id=closed_by_user_id,
    )


@moderation_cases_router.get(
    "/cases/{server_id}/{case_id}/users",
    response_model=list[ModerationCaseUserReadModel],
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_case_users(
    server_id: int,
    case_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await list_case_users_service(session=session, server_id=server_id, case_id=case_id)


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/users",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def add_user_to_case(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseUserAddModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    added_by_user_id = resolve_actor_user_id(body.added_by_user_id, current_user_id)
    return await add_user_to_case_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        user_id=int(body.user_id),
        role=body.role,
        added_by_user_id=added_by_user_id,
    )


@moderation_cases_router.delete(
    "/cases/{server_id}/{case_id}/users/{user_id}",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def remove_user_from_case(
    server_id: int,
    case_id: UUID,
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    return await remove_user_from_case_service(session=session, server_id=server_id, case_id=case_id, user_id=user_id)


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/notes",
    response_model=ModerationCaseNoteReadModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def add_moderation_case_note(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseNoteCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    author_user_id = resolve_actor_user_id(body.author_user_id, current_user_id)
    return await add_case_note_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        body=body,
        author_user_id=author_user_id,
    )


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/evidence",
    response_model=ModerationCaseEvidenceReadModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def add_moderation_case_evidence(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseEvidenceCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    added_by_user_id = resolve_actor_user_id(body.added_by_user_id, current_user_id)
    return await add_case_evidence_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        body=body,
        added_by_user_id=added_by_user_id,
    )


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/evidence/upload-url",
    response_model=ModerationEvidenceUploadUrlResponse,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def create_evidence_upload_url(
    server_id: int,
    case_id: UUID,
    body: ModerationEvidenceUploadUrlRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    await get_case_or_404(server_id, case_id, session)
    key = safe_upload_key(server_id, case_id, body.filename)
    upload_url = str(request.base_url) + f"moderation/evidence/upload/{key}"
    return ModerationEvidenceUploadUrlResponse(upload_url=upload_url, key=key, method="PUT")


@moderation_cases_router.put(
    "/evidence/upload/{key}",
    response_model=ModerationEvidenceUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_evidence_blob(
    key: str,
    payload: bytes = Body(...),
    content_type: str | None = Header(default=None, alias="Content-Type"),
):
    return store_evidence_blob(key=key, payload=payload, content_type=content_type)


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/actions",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def link_action_to_moderation_case(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseActionLinkCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    linked_by_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
    return await link_action_to_case_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        moderation_action_id=body.moderation_action_id,
        linked_by_user_id=linked_by_user_id,
    )


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/rules",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def upsert_moderation_case_rules(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseRulesUpsertModel,
    session: AsyncSession = Depends(get_session),
):
    return await upsert_case_rules_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        body=body,
    )


@moderation_cases_router.delete(
    "/cases/{server_id}/{case_id}/rules/{rule_id}",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def delete_moderation_case_rule(
    server_id: int,
    case_id: UUID,
    rule_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await remove_case_rule_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        rule_id=rule_id,
    )


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/actions/create",
    response_model=ModerationActionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def create_moderation_action_from_case(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseActionCreateFromCaseModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    actor_user_id = resolve_actor_user_id(None, current_user_id)
    return await create_action_from_case_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        body=body,
        actor_user_id=actor_user_id,
    )
