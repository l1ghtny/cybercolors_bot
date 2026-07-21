from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class BotMessageCreateModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    content: str = Field(min_length=1, max_length=2000)
    reply_to_message_id: str | None = Field(default=None, pattern=r"^\d+$")
    notify_replied_user: bool = False

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value


class BotMessageAuditReadModel(BaseModel):
    id: UUID
    server_id: str
    channel_id: str
    discord_message_id: str | None = None
    reply_to_message_id: str | None = None
    actor_user_id: str
    source: Literal["dashboard", "discord_context"]
    status: Literal["pending", "sent", "failed"]
    content: str
    error_text: str | None = None
    created_at: datetime
    sent_at: datetime | None = None
    jump_url: str | None = None
