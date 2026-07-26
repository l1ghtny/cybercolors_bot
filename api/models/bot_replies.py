from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


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


def _normalize_discord_ids(value: list[str], field_name: str) -> list[str]:
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
        raise ValueError(
            f"{field_name} must contain only Discord numeric IDs. Invalid values: {sample}",
        )
    return normalized


class ReplySettingsModel(BaseModel):
    server_id: str
    included_channel_ids: list[str] = Field(default_factory=list)
    excluded_channel_ids: list[str] = Field(default_factory=list)
    excluded_role_ids: list[str] = Field(default_factory=list)
    excluded_user_ids: list[str] = Field(default_factory=list)


class ReplySettingsUpdateModel(BaseModel):
    included_channel_ids: list[str] = Field(default_factory=list, max_length=500)
    excluded_channel_ids: list[str] = Field(default_factory=list, max_length=500)
    excluded_role_ids: list[str] = Field(default_factory=list, max_length=500)
    excluded_user_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator(
        "included_channel_ids",
        "excluded_channel_ids",
        "excluded_role_ids",
        "excluded_user_ids",
    )
    @classmethod
    def validate_discord_ids(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _normalize_discord_ids(value, info.field_name)

    @model_validator(mode="after")
    def validate_channel_lists_do_not_overlap(self):
        overlap = set(self.included_channel_ids).intersection(self.excluded_channel_ids)
        if overlap:
            raise ValueError("A channel cannot be both included and excluded")
        return self


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
