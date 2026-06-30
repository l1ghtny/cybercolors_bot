from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.models.moderation_cases import ModerationActorModel

AISuggestionStatusFilter = Literal[
    "pending",
    "pending_review",
    "action_requested",
    "case_created",
    "case_linked",
    "action_applied",
    "dismissed",
    "no_action_needed",
    "all",
]
AIActionType = Literal["warn", "mute", "kick", "ban"]


class AIChannelRefModel(BaseModel):
    id: str
    mention: str
    name: str | None = None


class AIMessageSnapshotModel(BaseModel):
    id: str
    content: str | None = None
    attachments: list[dict] = Field(default_factory=list)
    jump_url: str | None = None
    channel_deleted: bool = False
    archive_channel_id: str | None = None
    archive_message_id: str | None = None
    archive_jump_url: str | None = None


class AIModerationDecisionModel(BaseModel):
    id: str
    server_id: str
    message: AIMessageSnapshotModel
    channel: AIChannelRefModel
    author: ModerationActorModel
    ai_reason: str | None = None
    ai_categories: list[str] = Field(default_factory=list)
    confidence: float | None = None
    severity: str
    suggested_action: str
    selected_action: str | None = None
    action_reason: str | None = None
    action_override: bool = False
    rule_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    total_tokens: int = 0
    strictness: str
    status: str
    flagged: bool
    parse_error: str | None = None
    review_channel_id: str | None = None
    review_message_id: str | None = None
    linked_case_id: str | None = None
    linked_action_id: str | None = None
    reviewed_by: ModerationActorModel | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AIModerationDecisionListModel(BaseModel):
    items: list[AIModerationDecisionModel] = Field(default_factory=list)
    next_cursor: str | None = None
    unread_count: int = 0


class AIApproveSuggestionModel(BaseModel):
    override_action: AIActionType | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=525600)
    rule_ids: list[str] | None = None
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AITweakSuggestionModel(BaseModel):
    action: AIActionType
    duration_minutes: int | None = Field(default=None, ge=1, le=525600)
    rule_ids: list[str] | None = None
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AIDismissSuggestionModel(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AIResolveSuggestionResponseModel(BaseModel):
    suggestion: AIModerationDecisionModel
    action_id: str | None = None
