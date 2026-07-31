from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class BotMessageCreateModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    content: str = Field(default="", max_length=2000)
    reply_to_message_id: str | None = Field(default=None, pattern=r"^\d+$")
    notify_replied_user: bool = False
    suppress_mentions: bool = False
    mention_user_ids: list[str] = Field(default_factory=list, max_length=100)
    mention_role_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("mention_user_ids", "mention_role_ids")
    @classmethod
    def normalize_mention_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(value) for value in values))
        if any(not value.isdigit() for value in normalized):
            raise ValueError("Mention ids must be Discord snowflakes")
        return normalized


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
