from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import select, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Optional
import uuid
from datetime import datetime

# Import your dependency and new models
from src.db.database import get_session
from src.db.models import ModerationAction, ActionType, GlobalUser
from src.modules.moderation.moderation import check_if_user_exists, check_if_server_exists

moderation = APIRouter(prefix="/moderation", tags=["moderation"])

# Define a Pydantic model for creating a new action (for request body validation)
class ModerationActionCreate(BaseModel):
    action_type: ActionType
    moderator_user_id: int
    reason: str
    expires_at: datetime | None = None

    # Add fields needed to create user/server if they don't exist
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


@moderation.post("/create_action", response_model=ModerationAction)
async def create_moderation_action(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_session)
):
    """
    Logs a new moderation action (warn, mute, ban).
    This endpoint would be called by the bot.
    """
    # Create mock objects that mimic discord.py's structure for our validation functions
    mock_user = type('MockUser', (), {
        'id': action.target_user_id,
        'name': action.target_user_name,
        'joined_at': action.target_user_joined_at,
        'nick': action.target_user_server_nickname
    })()
    mock_server = type('MockServer', (), {'id': action.server_id, 'name': action.server_name})()

    # Ensure server and user exist in the database, creating them if needed.
    # These functions will add to the session but not commit.
    await check_if_server_exists(mock_server, session)
    await check_if_user_exists(mock_user, mock_server, session)

    db_action = ModerationAction.model_validate(action)
    session.add(db_action)
    await session.flush()
    # The commit is handled automatically by the `get_session` dependency.
    await session.refresh(db_action)
    return db_action


@moderation.get("/history/{server_id}/get_user_history", response_model=List[ModerationActionRead])
async def get_user_history(
        server_id: int,
        search: str = Query(..., description="The ID or username of the user to search for."),
        session: AsyncSession = Depends(get_session)
):
    """
    Gets all moderation actions for a specific user on a server,
    searching by either user ID or username.
    """
    target_user_id: int

    if search.isdigit():
        target_user_id = int(search)
    else:
        user_result = await session.exec(select(GlobalUser).where(GlobalUser.username == search))
        user = user_result.one_or_none()
        if not user:
            return []
        target_user_id = user.discord_id

    statement = select(ModerationAction).where(
        ModerationAction.server_id == server_id,
        ModerationAction.target_user_id == target_user_id
    ).options(selectinload(ModerationAction.global_user_moderator)).order_by(ModerationAction.created_at)

    result = await session.exec(statement)
    actions = result.all()

    # **Convert to the Read model to ensure IDs are strings**
    return await _return_moderation_history(actions)


@moderation.get('/history/{server_id}/', response_model=List[ModerationActionRead])
async def get_server_moderation_history(server_id: int, session: AsyncSession = Depends(get_session)):

    statement = select(ModerationAction).where(
        ModerationAction.server_id == server_id
    ).options(selectinload(ModerationAction.global_user_moderator), selectinload(ModerationAction.global_user_target)).order_by(ModerationAction.created_at)

    result = (await session.exec(statement)).all()
    return await _return_moderation_history(result)


async def _return_moderation_history(
        result
):
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
            is_active=action.is_active
        ) for action in result
    ]