from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel


class ReplyAddModel(BaseModel):
    user_message: str
    bot_reply: str
    server_id: str
    admin_id: str


class ReplyEditModel(BaseModel):
    id: UUID
    user_message: str
    bot_reply: str


class UserAvatarModel(BaseModel):
    avatar_url: str
    global_name: str


class ReplyModel(BaseModel):
    id: str
    user_messages: List[str]
    bot_reply: str
    created_at: datetime
    created_by: UserAvatarModel
