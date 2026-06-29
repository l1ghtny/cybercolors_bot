from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AIChannelMode = Literal["none", "all", "selected"]
AIModerationStrictness = Literal["low", "standard", "high"]
AIModerationActionMode = Literal["review_only"]


def _normalize_discord_ids(value: list[str] | None, field_name: str) -> list[str] | None:
    if value is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for raw_id in value:
        item_id = str(raw_id).strip()
        if not item_id.isdigit():
            invalid.append(str(raw_id))
            continue
        if item_id not in seen:
            seen.add(item_id)
            normalized.append(item_id)
    if invalid:
        sample = ", ".join(invalid[:5])
        raise ValueError(f"{field_name} must contain only Discord numeric IDs. Invalid values: {sample}")
    return normalized


class ServerAISettingsReadModel(BaseModel):
    server_id: str
    answer_channel_mode: AIChannelMode
    answer_allowed_channel_ids: list[str] = Field(default_factory=list)
    answer_allowed_role_ids: list[str] = Field(default_factory=list)
    moderation_enabled: bool
    moderation_channel_mode: AIChannelMode
    moderation_included_channel_ids: list[str] = Field(default_factory=list)
    moderation_monitor_attachments: bool
    moderation_monitor_bots: bool
    moderation_strictness: AIModerationStrictness
    moderation_action_mode: AIModerationActionMode
    log_ai_decisions: bool
    updated_at: datetime


class ServerAISettingsUpdateModel(BaseModel):
    answer_channel_mode: AIChannelMode | None = None
    answer_allowed_channel_ids: list[str] | None = None
    answer_allowed_role_ids: list[str] | None = None
    moderation_enabled: bool | None = None
    moderation_channel_mode: AIChannelMode | None = None
    moderation_included_channel_ids: list[str] | None = None
    moderation_monitor_attachments: bool | None = None
    moderation_monitor_bots: bool | None = None
    moderation_strictness: AIModerationStrictness | None = None
    moderation_action_mode: AIModerationActionMode | None = None
    log_ai_decisions: bool | None = None

    @field_validator("answer_allowed_channel_ids")
    @classmethod
    def validate_answer_channel_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "answer_allowed_channel_ids")

    @field_validator("answer_allowed_role_ids")
    @classmethod
    def validate_answer_role_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "answer_allowed_role_ids")

    @field_validator("moderation_included_channel_ids")
    @classmethod
    def validate_moderation_channel_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "moderation_included_channel_ids")

    @model_validator(mode="after")
    def validate_selected_modes(self):
        if self.answer_channel_mode == "selected" and self.answer_allowed_channel_ids == []:
            raise ValueError("answer_allowed_channel_ids cannot be empty when answer_channel_mode is selected")
        if self.moderation_channel_mode == "selected" and self.moderation_included_channel_ids == []:
            raise ValueError("moderation_included_channel_ids cannot be empty when moderation_channel_mode is selected")
        return self
