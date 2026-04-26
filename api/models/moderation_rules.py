from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from api.models.moderation_cases import ModerationActorModel
from src.db.models import CaseStatus


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
    usage_count: int | None = None
    last_cited_at: datetime | None = None


class ModerationRuleImportTextModel(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    replace_existing: bool = True
    created_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationRuleImportMessageModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    message_id: str = Field(pattern=r"^\d+$")
    replace_existing: bool = True
    created_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class ModerationRuleMessageRefModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    message_id: str = Field(pattern=r"^\d+$")


class ModerationRuleImportMessagesModel(BaseModel):
    messages: list[ModerationRuleMessageRefModel] = Field(min_length=1, max_length=100)
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


class ModerationRuleParseGuideModel(BaseModel):
    title: str
    guidance: list[str]
    example: str


class RuleUsageActionSummaryModel(BaseModel):
    id: str
    action_type: str
    target_user: ModerationActorModel
    moderator: ModerationActorModel
    reason: str
    created_at: datetime
    expires_at: datetime | None = None
    is_active: bool


class RuleUsageCaseSummaryModel(BaseModel):
    id: str
    title: str
    status: CaseStatus
    created_at: datetime
    target_user: ModerationActorModel


class RuleUsageTopOffenderModel(BaseModel):
    user: ModerationActorModel
    action_count: int


class ModerationRuleUsageModel(BaseModel):
    rule: ModerationRuleReadModel
    action_count: int
    case_count: int
    last_cited_at: datetime | None = None
    recent_actions: list[RuleUsageActionSummaryModel] = Field(default_factory=list)
    recent_cases: list[RuleUsageCaseSummaryModel] = Field(default_factory=list)
    top_offenders: list[RuleUsageTopOffenderModel] = Field(default_factory=list)
