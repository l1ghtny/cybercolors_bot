from datetime import datetime

from pydantic import BaseModel

from src.db.models import ActionType


class ModerationActionCreate(BaseModel):
    action_type: ActionType
    moderator_user_id: int | None = None
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
    expires_at: datetime | None = None
    is_active: bool
