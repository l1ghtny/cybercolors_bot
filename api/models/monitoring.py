from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from api.models.moderation_cases import ModerationActorModel


class MonitoredUserCreateModel(BaseModel):
    user_id: str = Field(pattern=r"^\d+$")
    reason: str | None = Field(default=None, max_length=5000)
    added_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class MonitoredUserUpdateModel(BaseModel):
    reason: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None
    updated_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @model_validator(mode="after")
    def validate_payload(self):
        if self.reason is None and self.is_active is None:
            raise ValueError("At least one of reason or is_active must be provided")
        return self


class MonitoredUserReadModel(BaseModel):
    id: str
    server_id: str
    reason: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    user: ModerationActorModel
    added_by: ModerationActorModel


class MonitoredUserCommentCreateModel(BaseModel):
    comment: str = Field(min_length=1, max_length=10000)
    author_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("comment cannot be empty")
        return cleaned


class MonitoredUserCommentReadModel(BaseModel):
    id: str
    monitored_user_id: str
    comment: str
    created_at: datetime
    author: ModerationActorModel


class MonitoredUserStatusEventReadModel(BaseModel):
    id: str
    monitored_user_id: str
    from_is_active: bool | None = None
    to_is_active: bool
    changed_at: datetime
    changed_by: ModerationActorModel
