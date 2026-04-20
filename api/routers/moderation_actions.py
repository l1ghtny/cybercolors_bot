from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_optional_current_discord_user_id, resolve_actor_user_id
from api.models.moderation_actions import ModerationActionCreate, ModerationActionRead
from api.models.moderation_cases import DeletedMessageCreateModel, DeletedMessageLinkModel, DeletedMessageReadModel
from api.services.discord_guilds import fetch_guild_channels
from api.services.moderation_core import build_actor, naive_utcnow, to_deleted_message_read, to_moderation_history
from api.services.moderation_queries import (
    query_deleted_messages,
    query_deleted_messages_for_action,
    query_moderation_actions,
)
from src.db.database import get_session
from src.db.models import (
    DeletedMessage,
    GlobalUser,
    ModerationAction,
    ModerationActionDeletedMessageLink,
)
from src.modules.moderation.moderation_helpers import check_if_server_exists, check_if_user_exists

moderation_actions_router = APIRouter()


@moderation_actions_router.post("/create_action", response_model=ModerationAction)
async def create_moderation_action(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
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

    moderator_user_id = current_user_id if current_user_id is not None else action.moderator_user_id
    if moderator_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="moderator_user_id is required (or use Bearer token)",
        )

    db_action = ModerationAction(
        action_type=action.action_type,
        moderator_user_id=moderator_user_id,
        reason=action.reason,
        expires_at=action.expires_at,
        target_user_id=action.target_user_id,
        server_id=action.server_id,
    )
    session.add(db_action)
    await session.flush()
    await session.refresh(db_action)
    return db_action


@moderation_actions_router.get("/history/{server_id}/get_user_history", response_model=List[ModerationActionRead])
async def get_user_history(
    server_id: int,
    search: str = Query(..., description="The ID or username of the user to search for."),
    session: AsyncSession = Depends(get_session),
):
    if search.isdigit():
        target_user_id = int(search)
    else:
        user_result = await session.exec(select(GlobalUser).where(GlobalUser.username == search))
        user = user_result.one_or_none()
        if not user:
            return []
        target_user_id = user.discord_id

    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=target_user_id,
    )
    return to_moderation_history(actions)


@moderation_actions_router.get("/history/{server_id}/", response_model=List[ModerationActionRead])
async def get_server_moderation_history(
    server_id: int,
    target_user_id: str | None = Query(default=None, pattern=r"^\d+$"),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=int(target_user_id) if target_user_id else None,
        limit=limit,
    )
    return to_moderation_history(actions)


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
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    server_id = action.server_id
    linked_by_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
    await build_actor(session, server_id, linked_by_user_id, require_membership=True)

    author_user_id = int(body.author_user_id) if body.author_user_id else None
    deleted_by_user_id = int(body.deleted_by_user_id) if body.deleted_by_user_id else None
    if author_user_id:
        await build_actor(session, server_id, author_user_id)
    if deleted_by_user_id:
        await build_actor(session, server_id, deleted_by_user_id)

    deleted_message = DeletedMessage(
        server_id=server_id,
        message_id=int(body.message_id),
        channel_id=int(body.channel_id),
        author_user_id=author_user_id,
        content=body.content,
        attachments_json=body.attachments_json,
        deleted_at=body.deleted_at or naive_utcnow(),
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

    return await to_deleted_message_read(deleted_message, session)


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
    action = await session.get(ModerationAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation action not found")

    deleted_message = await session.get(DeletedMessage, deleted_message_id)
    if not deleted_message or deleted_message.server_id != action.server_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deleted message not found")

    linked_by_user_id = resolve_actor_user_id(body.linked_by_user_id, current_user_id)
    await build_actor(session, action.server_id, linked_by_user_id, require_membership=True)

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

    return await to_deleted_message_read(
        deleted_message,
        session,
        channel_name=channel_names.get(deleted_message.channel_id),
    )


@moderation_actions_router.get("/actions/{action_id}/deleted-messages", response_model=list[DeletedMessageReadModel])
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
        await to_deleted_message_read(item, session, channel_name=channel_names.get(item.channel_id))
        for item in deleted_messages
    ]


@moderation_actions_router.get("/deleted-messages/{server_id}", response_model=list[DeletedMessageReadModel])
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
        await to_deleted_message_read(item, session, channel_name=channel_names.get(item.channel_id))
        for item in messages
    ]
