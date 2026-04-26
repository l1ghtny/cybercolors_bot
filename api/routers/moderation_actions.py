from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import (
    get_current_discord_user_id,
    get_optional_current_discord_user_id,
    resolve_actor_user_id,
)
from api.dependencies.server_access import require_server_dashboard_access
from api.services.dashboard_access_service import assert_dashboard_access
from api.models.moderation_actions import ModerationActionCreate, ModerationActionRead
from api.models.moderation_cases import DeletedMessageCreateModel, DeletedMessageLinkModel, DeletedMessageReadModel
from api.services.moderation_core import to_moderation_history
from api.services.moderation_actions_service import (
    add_deleted_message_for_action as add_deleted_message_for_action_service,
    browse_deleted_messages_for_server,
    create_action as create_action_service,
    get_deleted_messages_for_action as get_deleted_messages_for_action_service,
    get_server_history,
    get_user_history_by_search,
    link_existing_deleted_message_to_action as link_existing_deleted_message_to_action_service,
)
from src.db.database import get_session
from src.db.models import ModerationAction

moderation_actions_router = APIRouter()


async def _assert_action_dashboard_access(
    session: AsyncSession,
    action_id: UUID,
    caller_user_id: int,
    access_token: str,
) -> ModerationAction:
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")
    await assert_dashboard_access(
        session=session,
        server_id=action.server_id,
        caller_user_id=caller_user_id,
        access_token=access_token,
    )
    return action


async def require_action_body_dashboard_access(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
    await assert_dashboard_access(
        session=session,
        server_id=action.server_id,
        caller_user_id=current_user_id,
        access_token=access_token,
    )
    return current_user_id


async def require_action_deleted_message_dashboard_access(
    action_id: UUID,
    body: DeletedMessageCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
    caller_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
    await _assert_action_dashboard_access(
        session=session,
        action_id=action_id,
        caller_user_id=caller_user_id,
        access_token=access_token,
    )
    return caller_user_id


async def require_action_deleted_message_link_dashboard_access(
    action_id: UUID,
    body: DeletedMessageLinkModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> int:
    linked_by_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
    await _assert_action_dashboard_access(
        session=session,
        action_id=action_id,
        caller_user_id=linked_by_user_id,
        access_token=access_token,
    )
    return linked_by_user_id


async def require_action_read_dashboard_access(
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(get_current_discord_user_id),
    access_token: str = Depends(get_bearer_access_token),
) -> None:
    await _assert_action_dashboard_access(
        session=session,
        action_id=action_id,
        caller_user_id=current_user_id,
        access_token=access_token,
    )


@moderation_actions_router.post("/create_action", response_model=ModerationActionRead, deprecated=True)
async def create_moderation_action(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_action_body_dashboard_access),
):
    created = await create_action_service(session=session, action=action, moderator_user_id=current_user_id)
    return to_moderation_history([created])[0]


@moderation_actions_router.post("/actions", response_model=ModerationActionRead)
async def create_moderation_action_v2(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_action_body_dashboard_access),
):
    created = await create_action_service(session=session, action=action, moderator_user_id=current_user_id)
    return to_moderation_history([created])[0]


@moderation_actions_router.get(
    "/history/{server_id}/get_user_history",
    response_model=List[ModerationActionRead],
    deprecated=True,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_user_history(
    server_id: int,
    search: str = Query(..., description="The ID or username of the user to search for."),
    session: AsyncSession = Depends(get_session),
):
    return await get_user_history_by_search(session=session, server_id=server_id, search=search)


@moderation_actions_router.get(
    "/history/{server_id}/users",
    response_model=List[ModerationActionRead],
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_user_history_v2(
    server_id: int,
    search: str = Query(..., description="The ID or username of the user to search for."),
    session: AsyncSession = Depends(get_session),
):
    return await get_user_history_by_search(session=session, server_id=server_id, search=search)


@moderation_actions_router.get(
    "/history/{server_id}/",
    response_model=List[ModerationActionRead],
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_server_moderation_history(
    server_id: int,
    target_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    return await get_server_history(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id,
        limit=limit,
    )


@moderation_actions_router.get(
    "/history/{server_id}",
    response_model=List[ModerationActionRead],
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_server_moderation_history_v2(
    server_id: int,
    target_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    return await get_server_history(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id,
        limit=limit,
    )


@moderation_actions_router.post(
    "/actions/{action_id}/deleted-messages",
    response_model=DeletedMessageReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_deleted_message_for_action(
    action_id: UUID,
    body: DeletedMessageCreateModel,
    session: AsyncSession = Depends(get_session),
    linked_by_user_id: int = Depends(require_action_deleted_message_dashboard_access),
):
    return await add_deleted_message_for_action_service(
        session=session,
        action_id=action_id,
        body=body,
        linked_by_user_id=linked_by_user_id,
    )


@moderation_actions_router.post(
    "/actions/{action_id}/deleted-messages/{deleted_message_id}/link",
    response_model=DeletedMessageReadModel,
)
async def link_existing_deleted_message_to_action(
    action_id: UUID,
    deleted_message_id: UUID,
    body: DeletedMessageLinkModel,
    session: AsyncSession = Depends(get_session),
    linked_by_user_id: int = Depends(require_action_deleted_message_link_dashboard_access),
):
    return await link_existing_deleted_message_to_action_service(
        session=session,
        action_id=action_id,
        deleted_message_id=deleted_message_id,
        linked_by_user_id=linked_by_user_id,
    )


@moderation_actions_router.get("/actions/{action_id}/deleted-messages", response_model=list[DeletedMessageReadModel])
async def get_deleted_messages_for_action(
    action_id: UUID,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_action_read_dashboard_access),
):
    return await get_deleted_messages_for_action_service(session=session, action_id=action_id)


@moderation_actions_router.get(
    "/deleted-messages/{server_id}",
    response_model=list[DeletedMessageReadModel],
    dependencies=[Depends(require_server_dashboard_access)],
)
async def browse_deleted_messages(
    server_id: int,
    author_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    channel_id: str | None = Query(default=None, pattern=r"^\d+$"),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    return await browse_deleted_messages_for_server(
        session=session,
        server_id=server_id,
        author_user_id=author_user_id,
        channel_id=channel_id,
        since=since,
        limit=limit,
    )
