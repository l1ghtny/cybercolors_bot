from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field


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


class ReplyDuplicateRequestModel(BaseModel):
    target_server_id: str = Field(pattern=r"^\d+$")
    reply_ids: list[UUID] = Field(min_length=1, max_length=500)


class ReplyDuplicateResponseModel(BaseModel):
    source_server_id: str
    target_server_id: str
    requested_replies: int
    duplicated_replies: int
    reused_replies: int
    duplicated_triggers: int
    skipped_triggers: int
    missing_reply_ids: list[str] = Field(default_factory=list)


class ReplyMutationResponseModel(BaseModel):
    success: bool = True
    processed: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
