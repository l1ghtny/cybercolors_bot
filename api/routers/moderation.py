from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List
import uuid
from datetime import datetime

# Import your dependency and new models
from src.db.database import get_session
from src.db.models import ModerationAction, ActionType
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


@moderation.post("/", response_model=ModerationAction)
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

@moderation.get("/history/{server_id}/{user_id}", response_model=List[ModerationAction])
async def get_user_history(
    server_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_session)
):
    """
    Gets all moderation actions for a specific user on a server.
    This will power the UI's user history page.
    """
    statement = select(ModerationAction).where(
        ModerationAction.server_id == server_id,
        ModerationAction.target_user_id == user_id
    ).order_by(ModerationAction.created_at)
    
    result = await session.exec(statement)
    actions = result.all()
    return actions