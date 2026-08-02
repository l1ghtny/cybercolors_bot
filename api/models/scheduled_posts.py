from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class ScheduledPostWriteModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    content: str = Field(min_length=1, max_length=2000)
    mention_everyone: bool = False
    mention_user_ids: list[str] = Field(default_factory=list, max_length=100)
    mention_role_ids: list[str] = Field(default_factory=list, max_length=100)
    schedule_type: Literal["once", "interval"]
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    next_run_at: datetime
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)

    @field_validator("mention_user_ids", "mention_role_ids")
    @classmethod
    def normalize_mention_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(value) for value in values))
        if any(not value.isdigit() for value in normalized):
            raise ValueError("Mention ids must be Discord snowflakes")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Use a valid IANA timezone") from error
        return value

    @field_validator("next_run_at")
    @classmethod
    def normalize_next_run_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("next_run_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.content.strip():
            raise ValueError("Message content cannot be blank")
        if self.schedule_type == "interval" and self.interval_seconds is None:
            raise ValueError("interval_seconds is required for recurring posts")
        if self.schedule_type == "once":
            self.interval_seconds = None
        return self


class ScheduledPostReadModel(BaseModel):
    id: UUID
    server_id: str
    channel_id: str
    content: str
    mention_everyone: bool
    mention_user_ids: list[str]
    mention_role_ids: list[str]
    schedule_type: Literal["once", "interval"]
    timezone: str
    interval_seconds: int | None
    status: Literal["active", "paused", "completed"]
    next_run_at: datetime
    last_run_at: datetime | None
    created_by_user_id: str
    updated_by_user_id: str
    created_at: datetime
    updated_at: datetime


class ScheduledPostRunReadModel(BaseModel):
    id: UUID
    scheduled_post_id: UUID
    scheduled_for: datetime
    status: Literal["claimed", "sent", "failed", "skipped"]
    bot_message_audit_id: UUID | None
    error_text: str | None
    created_at: datetime
    finished_at: datetime | None


class ScheduledPostStatusModel(BaseModel):
    status: Literal["active", "paused"]
