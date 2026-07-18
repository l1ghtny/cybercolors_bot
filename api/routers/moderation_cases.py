from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import (
    get_current_discord_user_id,
    get_optional_current_discord_user_id,
    resolve_actor_user_id,
)
from api.dependencies.server_access import require_server_permission
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
    ModerationCaseSummaryModel,
    ModerationCaseRulesUpsertModel,
    ModerationCaseStatusUpdateModel,
    ModerationCaseUserAddModel,
    ModerationCaseUserReadModel,
    ModerationEvidenceUploadUrlRequest,
    ModerationEvidenceDownloadUrlResponse,
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
    remove_action_from_case as remove_action_from_case_service,
    remove_user_from_case as remove_user_from_case_service,
    remove_case_rule as remove_case_rule_service,
    get_case_evidence_attachment,
    upsert_case_rules as upsert_case_rules_service,
    update_case_status as update_case_status_service,
)
from api.services.evidence_storage import create_download_ticket, create_upload_ticket
from api.services.rbac_service import assert_user_has_permission
from api.services.moderation_core import get_case_or_404
from src.db.database import get_session
from src.db.models import CaseStatus

moderation_cases_router = APIRouter()


async def require_case_action_apply_permission(
    server_id: int,
    body: ModerationCaseActionCreateFromCaseModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
    await assert_user_has_permission(
        session=session,
        server_id=server_id,
        user_id=current_user_id,
        permission_key=f"moderation.actions.apply.{body.action_type.value}",
        access_token=access_token,
    )
    return current_user_id


@moderation_cases_router.post(
    "/cases/{server_id}",
    response_model=ModerationCaseReadModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    response_model=List[ModerationCaseSummaryModel],
    dependencies=[Depends(require_server_permission("moderation.cases.view"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.view"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.view"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
)
async def create_evidence_upload_url(
    server_id: int,
    case_id: UUID,
    body: ModerationEvidenceUploadUrlRequest,
    session: AsyncSession = Depends(get_session),
):
    await get_case_or_404(server_id, case_id, session)
    return ModerationEvidenceUploadUrlResponse(
        **create_upload_ticket(
            server_id=server_id,
            case_id=case_id,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    )


@moderation_cases_router.get(
    "/cases/{server_id}/{case_id}/evidence/{evidence_id}/download-url",
    response_model=ModerationEvidenceDownloadUrlResponse,
    dependencies=[Depends(require_server_permission("moderation.cases.view"))],
)
async def create_evidence_download_url(
    server_id: int,
    case_id: UUID,
    evidence_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    evidence = await get_case_evidence_attachment(
        session=session,
        server_id=server_id,
        case_id=case_id,
        evidence_id=evidence_id,
    )
    return ModerationEvidenceDownloadUrlResponse(
        **create_download_ticket(
            key=str(evidence.attachment_key),
            filename=evidence.attachment_filename,
        )
    )


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/actions",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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


@moderation_cases_router.delete(
    "/cases/{server_id}/{case_id}/actions/{action_id}",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
)
async def unlink_action_from_moderation_case(
    server_id: int,
    case_id: UUID,
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    return await remove_action_from_case_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        action_id=action_id,
    )


@moderation_cases_router.post(
    "/cases/{server_id}/{case_id}/rules",
    response_model=ModerationCaseReadModel,
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
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
    dependencies=[Depends(require_server_permission("moderation.cases.manage"))],
)
async def create_moderation_action_from_case(
    server_id: int,
    case_id: UUID,
    body: ModerationCaseActionCreateFromCaseModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_case_action_apply_permission),
):
    return await create_action_from_case_service(
        session=session,
        server_id=server_id,
        case_id=case_id,
        body=body,
        actor_user_id=current_user_id,
        apply_discord_effects=True,
    )
