from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List
import uuid
from datetime import datetime

# Import your dependency and new models
from api.db_operations.dependencies import get_db_session
from src.db.models import ModerationAction, ActionType

moderation = APIRouter(prefix="/moderation", tags=["moderation"])

# Define a Pydantic model for creating a new action (for request body validation)
class ModerationActionCreate(SQLModel):
    action_type: ActionType
    server_id: int
    target_user_id: int
    moderator_user_id: int
    reason: str
    expires_at: datetime | None = None

@moderation.post("/", response_model=ModerationAction)
async def create_moderation_action(
    action: ModerationActionCreate,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Logs a new moderation action (warn, mute, ban).
    This endpoint would be called by the bot.
    """
    db_action = ModerationAction.from_orm(action)
    session.add(db_action)
    await session.commit()
    await session.refresh(db_action)
    return db_action

@moderation.get("/history/{server_id}/{user_id}", response_model=List[ModerationAction])
async def get_user_history(
    server_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Gets all moderation actions for a specific user on a server.
    This will power the UI's user history page.
    """
    statement = select(ModerationAction).where(
        ModerationAction.server_id == server_id,
        ModerationAction.target_user_id == user_id
    ).order_by(ModerationAction.created_at.desc())
    
    result = await session.exec(statement)
    actions = result.all()
    return actions