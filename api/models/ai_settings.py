from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AIChannelMode = Literal["none", "all", "selected", "exclude_selected"]
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


class ServerAISettingsPermissionsModel(BaseModel):
    can_edit: bool = False


class ServerAISettingsReadModel(BaseModel):
    server_id: str
    answer_enabled: bool
    answer_channel_mode: AIChannelMode
    answer_allowed_channel_ids: list[str] = Field(default_factory=list)
    answer_allowed_role_ids: list[str] = Field(default_factory=list)
    moderation_enabled: bool
    moderation_channel_mode: AIChannelMode
    moderation_included_channel_ids: list[str] = Field(default_factory=list)
    moderation_excluded_channel_ids: list[str] = Field(default_factory=list)
    moderation_monitor_attachments: bool
    moderation_monitor_bots: bool
    moderation_strictness: AIModerationStrictness
    moderation_action_mode: AIModerationActionMode
    moderation_review_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    log_ai_decisions: bool
    moderation_kill_switch_enabled: bool
    moderation_daily_token_limit: int | None = Field(default=None, ge=1)
    moderation_provider_timeout_seconds: int = Field(default=20, ge=1, le=120)
    answer_persona: str | None = Field(default=None, max_length=1200)
    server_brief: str | None = Field(default=None, max_length=600)
    knowledge_subject_priority_role_ids: list[str] = Field(default_factory=list)
    updated_at: datetime
    permissions: ServerAISettingsPermissionsModel = Field(default_factory=ServerAISettingsPermissionsModel)


class ServerAISettingsUpdateModel(BaseModel):
    answer_enabled: bool | None = None
    answer_channel_mode: AIChannelMode | None = None
    answer_allowed_channel_ids: list[str] | None = None
    answer_allowed_role_ids: list[str] | None = None
    moderation_enabled: bool | None = None
    moderation_channel_mode: AIChannelMode | None = None
    moderation_included_channel_ids: list[str] | None = None
    moderation_excluded_channel_ids: list[str] | None = None
    moderation_monitor_attachments: bool | None = None
    moderation_monitor_bots: bool | None = None
    moderation_strictness: AIModerationStrictness | None = None
    moderation_action_mode: AIModerationActionMode | None = None
    moderation_review_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    log_ai_decisions: bool | None = None
    moderation_kill_switch_enabled: bool | None = None
    moderation_daily_token_limit: int | None = Field(default=None, ge=1)
    moderation_provider_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    answer_persona: str | None = Field(default=None, max_length=1200)
    server_brief: str | None = Field(default=None, max_length=600)
    knowledge_subject_priority_role_ids: list[str] | None = None

    @field_validator("answer_allowed_channel_ids")
    @classmethod
    def validate_answer_channel_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "answer_allowed_channel_ids")

    @field_validator("answer_allowed_role_ids")
    @classmethod
    def validate_answer_role_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "answer_allowed_role_ids")

    @field_validator("knowledge_subject_priority_role_ids")
    @classmethod
    def validate_knowledge_priority_role_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "knowledge_subject_priority_role_ids")

    @field_validator("moderation_included_channel_ids")
    @classmethod
    def validate_moderation_channel_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "moderation_included_channel_ids")

    @field_validator("moderation_excluded_channel_ids")
    @classmethod
    def validate_moderation_excluded_channel_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_discord_ids(value, "moderation_excluded_channel_ids")

    @field_validator("moderation_review_channel_id", mode="before")
    @classmethod
    def normalize_review_channel_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or ""

    @field_validator("answer_persona", "server_brief")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_selected_modes(self):
        if self.answer_channel_mode == "selected" and self.answer_allowed_channel_ids == []:
            raise ValueError("answer_allowed_channel_ids cannot be empty when answer_channel_mode is selected")
        if self.moderation_channel_mode == "selected" and self.moderation_included_channel_ids == []:
            raise ValueError("moderation_included_channel_ids cannot be empty when moderation_channel_mode is selected")
        if self.moderation_channel_mode == "exclude_selected" and self.moderation_excluded_channel_ids == []:
            raise ValueError("moderation_excluded_channel_ids cannot be empty when moderation_channel_mode is exclude_selected")
        return self


class AIChannelPermissionHealthModel(BaseModel):
    channel_id: str | None = None
    channel_name: str | None = None
    purpose: Literal["moderation", "mod_log", "ai_review"]
    configured: bool = True
    exists: bool = False
    ok: bool = False
    can_view_channel: bool = False
    can_read_message_history: bool = False
    can_send_messages: bool | None = None
    can_embed_links: bool | None = None
    reason: str | None = None


class ServerAISettingsHealthModel(BaseModel):
    server_id: str
    ok: bool
    checked_at: datetime
    moderation_enabled: bool
    moderation_channel_mode: AIChannelMode
    moderation_channels: list[AIChannelPermissionHealthModel] = Field(default_factory=list)
    mod_log_channel: AIChannelPermissionHealthModel
    ai_review_channel: AIChannelPermissionHealthModel
    warnings: list[str] = Field(default_factory=list)
