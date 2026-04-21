from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ModerationRuleCreateModel(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    sort_order: int = Field(default=0, ge=0)
    created_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @field_validator("code", "title", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ModerationRuleReadModel(BaseModel):
    id: str
    server_id: str
    code: str | None = None
    title: str
    description: str | None = None
    sort_order: int
    source_channel_id: str | None = None
    source_message_id: str | None = None
    source_marker: str | None = None
    is_active: bool
    created_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ModerationRuleImportTextModel(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    replace_existing: bool = True
    created_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationRuleImportMessageModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    message_id: str = Field(pattern=r"^\d+$")
    replace_existing: bool = True
    created_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ParsedModerationRuleModel(BaseModel):
    marker: str | None = None
    code: str | None = None
    title: str
    description: str | None = None
    sort_order: int


class ModerationRuleParsePreviewModel(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class ModerationRuleBulkUpsertResponseModel(BaseModel):
    imported: list[ModerationRuleReadModel]
