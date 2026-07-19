from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from api.models.moderation_cases import ModerationRuleRef
from src.db.models import ActionType


class ModerationActionMessageCleanupCreate(BaseModel):
    message_ids: list[str] = Field(default_factory=list)
    recent_period_minutes: int | None = Field(default=None, ge=1, le=10080)
    recent_limit: int = Field(default=25, ge=1, le=100)
    channel_ids: list[str] = Field(default_factory=list)

    @field_validator("message_ids", "channel_ids")
    @classmethod
    def validate_discord_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            candidate = str(item).strip()
            if not candidate:
                continue
            if not candidate.isdigit():
                raise ValueError("Discord IDs must contain only digits")
            if candidate not in cleaned:
                cleaned.append(candidate)
        return cleaned

    @model_validator(mode="after")
    def validate_cleanup_requested(self):
        if not self.message_ids and self.recent_period_minutes is None:
            raise ValueError("Select message_ids or recent_period_minutes")
        return self


class ModerationMessageLogReadModel(BaseModel):
    message_id: str
    server_id: str
    channel_id: str
    channel_name: str | None = None
    author_user_id: str
    content: str
    created_at: datetime


class ModerationActionCreate(BaseModel):
    action_type: ActionType
    moderator_user_id: int | None = None
    reason: str | None = None
    rule_id: UUID | None = None
    rule_ids: list[str] = Field(default_factory=list)
    commentary: str | None = None
    expires_at: datetime | None = None
    case_id: str | None = None
    target_user_id: int
    target_user_name: str
    target_user_joined_at: datetime
    target_user_server_nickname: str | None
    server_id: int
    server_name: str
    message_cleanup: ModerationActionMessageCleanupCreate | None = None

    @field_validator("expires_at")
    @classmethod
    def normalize_expires_at(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @model_validator(mode="after")
    def validate_reason_or_rule(self):
        if self.rule_id is None and not self.rule_ids and (self.reason is None or not self.reason.strip()):
            raise ValueError("Either reason or rule_id must be provided")
        return self


class ModerationActionRead(BaseModel):
    id: str
    action_type: ActionType
    server_id: str
    target_user_id: str
    target_user_username: str
    moderator_user_id: str
    moderator_username: str
    reason: str
    rule_id: str | None = None
    rule_code: str | None = None
    rule_title: str | None = None
    rules: list[ModerationRuleRef] = Field(default_factory=list)
    case_id: str | None = None
    case_title: str | None = None
    commentary: str | None = None
    created_at: datetime
    created_at_label: str | None = None
    import_source: str | None = None
    import_source_label: str | None = None
    source_created_at_known: bool = True
    source_created_at_note: str | None = None
    expires_at: datetime | None = None
    is_active: bool
    is_reverted: bool = False


class ModerationActionSummaryModel(BaseModel):
    id: str
    action_type: ActionType
    server_id: str
    target_user_id: str
    target_user_username: str
    moderator_user_id: str
    moderator_username: str
    reason: str
    case_id: str | None = None
    case_title: str | None = None
    created_at: datetime
    created_at_label: str | None = None
    import_source: str | None = None
    import_source_label: str | None = None
    source_created_at_known: bool = True
    source_created_at_note: str | None = None
    expires_at: datetime | None = None
    is_active: bool
    is_reverted: bool = False
    rules_count: int = 0
    deleted_messages_count: int = 0


class ModerationActionRevertRequest(BaseModel):
    reason: str | None = None


class ModerationActionRevertRead(BaseModel):
    action: ModerationActionRead
    discord_changed: bool
