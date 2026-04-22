from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.db.models import CaseStatus


class UserActivityUpsertModel(BaseModel):
    channel_id: str = Field(pattern=r"^\d+$")
    increment: int = Field(default=1, ge=1, le=100)
    observed_at: datetime | None = None
    username: str | None = None
    server_nickname: str | None = None

    @field_validator("username", "server_nickname")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class UserActivityChannelCountModel(BaseModel):
    channel_id: str
    message_count: int


class UserActivitySummaryModel(BaseModel):
    user_id: str
    server_id: str
    message_count: int
    last_message_at: datetime | None = None
    channel_id: str | None = None
    channels: list[UserActivityChannelCountModel] = Field(default_factory=list)
    period_start: datetime | None = None
    period_end: datetime | None = None


class UserActivityLeaderboardItemModel(BaseModel):
    user_id: str
    username: str | None = None
    server_nickname: str | None = None
    display_name: str
    message_count: int
    last_message_at: datetime
    channels: list[UserActivityChannelCountModel] = Field(default_factory=list)
    period_start: datetime | None = None
    period_end: datetime | None = None


class NicknameLogModel(BaseModel):
    nickname: str = Field(min_length=1, max_length=128)
    server_name: str | None = Field(default=None, max_length=128)
    recorded_at: datetime | None = None

    @field_validator("nickname", "server_name")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class NicknameRecordModel(BaseModel):
    id: str
    user_id: str
    server_id: str | None = None
    server_name: str
    nickname: str
    recorded_at: datetime


class UserModerationActionSummaryModel(BaseModel):
    id: str
    action_type: str
    reason: str
    created_at: datetime
    moderator_user_id: str
    moderator_username: str | None = None


class UserModerationCaseSummaryModel(BaseModel):
    id: str
    title: str
    status: CaseStatus
    created_at: datetime


class UserProfileCardModel(BaseModel):
    user_id: str
    username: str | None = None
    server_nickname: str | None = None
    display_name: str
    avatar_hash: str | None = None
    joined_discord: datetime | None = None
    is_member: bool
    flagged_absent_at: datetime | None = None
    activity: UserActivitySummaryModel | None = None
    nickname_history: list[NicknameRecordModel]
    moderation_actions_count: int
    open_cases_count: int
    recent_actions: list[UserModerationActionSummaryModel]
    recent_cases: list[UserModerationCaseSummaryModel]
