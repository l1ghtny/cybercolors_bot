from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_optional_current_discord_user_id, resolve_actor_user_id
from api.models.moderation_actions import ModerationActionCreate, ModerationActionRead
from api.models.moderation_cases import DeletedMessageCreateModel, DeletedMessageLinkModel, DeletedMessageReadModel
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


@moderation_actions_router.post("/create_action", response_model=ModerationAction)
async def create_moderation_action(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    moderator_user_id = current_user_id if current_user_id is not None else action.moderator_user_id
    if moderator_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="moderator_user_id is required (or use Bearer token)",
        )
    return await create_action_service(session=session, action=action, moderator_user_id=moderator_user_id)


@moderation_actions_router.get("/history/{server_id}/get_user_history", response_model=List[ModerationActionRead])
async def get_user_history(
    server_id: int,
    search: str = Query(..., description="The ID or username of the user to search for."),
    session: AsyncSession = Depends(get_session),
):
    return await get_user_history_by_search(session=session, server_id=server_id, search=search)


@moderation_actions_router.get("/history/{server_id}/", response_model=List[ModerationActionRead])
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


@moderation_actions_router.post(
    "/actions/{action_id}/deleted-messages",
    response_model=DeletedMessageReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_deleted_message_for_action(
    action_id: UUID,
    body: DeletedMessageCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    linked_by_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
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
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    linked_by_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
    return await link_existing_deleted_message_to_action_service(
        session=session,
        action_id=action_id,
        deleted_message_id=deleted_message_id,
        linked_by_user_id=linked_by_user_id,
    )


@moderation_actions_router.get("/actions/{action_id}/deleted-messages", response_model=list[DeletedMessageReadModel])
async def get_deleted_messages_for_action(action_id: UUID, session: AsyncSession = Depends(get_session)):
    return await get_deleted_messages_for_action_service(session=session, action_id=action_id)


@moderation_actions_router.get("/deleted-messages/{server_id}", response_model=list[DeletedMessageReadModel])
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
