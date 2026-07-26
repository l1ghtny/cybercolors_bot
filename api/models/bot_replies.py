from datetime import datetime
import re
from typing import List, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class ReplyAddModel(BaseModel):
    user_message: str
    bot_reply: str
    server_id: str
    admin_id: str
    source: Literal["representative", "generated"] = "representative"


class ReplyEditModel(BaseModel):
    id: UUID
    user_message: str
    bot_reply: str
    source: Literal["representative", "generated"] = "representative"


class UserAvatarModel(BaseModel):
    avatar_url: str
    global_name: str


class ReplyModel(BaseModel):
    id: str
    user_messages: List[str]
    bot_reply: str
    created_at: datetime
    created_by: UserAvatarModel
    representative_questions: list[str] = Field(default_factory=list)
    generated_variations: list[str] = Field(default_factory=list)


def _normalize_phrases(values: list[str], *, max_items: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = " ".join(str(raw_value).split()).strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    if len(normalized) > max_items:
        raise ValueError(f"At most {max_items} phrases are allowed")
    return normalized


class ReplyIntentCreateModel(BaseModel):
    bot_reply: str = Field(min_length=1, max_length=4000)
    representative_questions: list[str] = Field(min_length=2, max_length=5)
    generated_variations: list[str] = Field(default_factory=list, max_length=100)
    admin_id: str = Field(pattern=r"^\d+$")

    @field_validator("representative_questions")
    @classmethod
    def normalize_representative_questions(cls, value: list[str]) -> list[str]:
        normalized = _normalize_phrases(value, max_items=5)
        if len(normalized) < 2:
            raise ValueError("Provide at least 2 distinct representative questions")
        return normalized

    @field_validator("generated_variations")
    @classmethod
    def normalize_generated_variations(cls, value: list[str]) -> list[str]:
        return _normalize_phrases(value, max_items=100)

    @field_validator("bot_reply")
    @classmethod
    def normalize_bot_reply(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def remove_generated_duplicates(self):
        representative = {item.casefold() for item in self.representative_questions}
        self.generated_variations = [
            item for item in self.generated_variations if item.casefold() not in representative
        ]
        return self


class ReplyIntentUpdateModel(ReplyIntentCreateModel):
    admin_id: str | None = Field(default=None, pattern=r"^\d+$")


class ReplyConceptCreateModel(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    variants: list[str] = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[\wа-яё-]+", normalized, flags=re.UNICODE):
            raise ValueError("Concept names may contain letters, numbers, underscores, and hyphens")
        return normalized

    @field_validator("variants")
    @classmethod
    def normalize_variants(cls, value: list[str]) -> list[str]:
        normalized = _normalize_phrases(value, max_items=100)
        if not normalized:
            raise ValueError("Provide at least one distinct concept variant")
        return normalized


class ReplyConceptUpdateModel(ReplyConceptCreateModel):
    pass


class ReplyConceptModel(BaseModel):
    id: str
    server_id: str
    name: str
    variants: list[str]


class ReplyVariationSuggestionRequestModel(BaseModel):
    bot_reply: str = Field(min_length=1, max_length=4000)
    representative_questions: list[str] = Field(min_length=2, max_length=5)

    @field_validator("representative_questions")
    @classmethod
    def normalize_questions(cls, value: list[str]) -> list[str]:
        normalized = _normalize_phrases(value, max_items=5)
        if len(normalized) < 2:
            raise ValueError("Provide at least 2 distinct representative questions")
        return normalized


class ReplyVariationSuggestionResponseModel(BaseModel):
    variations: list[str]
    model: str


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
