from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from api.models.moderation_cases import ModerationRuleRef
from src.db.models import ActionType


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
    expires_at: datetime | None = None
    is_active: bool
