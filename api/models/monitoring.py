from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from api.models.moderation_cases import ModerationActorModel
from src.db.models import CaseStatus


class MonitoredUserCreateModel(BaseModel):
    user_id: str = Field(pattern=r"^\d+$")
    reason: str | None = Field(default=None, max_length=5000)
    added_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class MonitoredUserUpdateModel(BaseModel):
    reason: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None
    updated_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @model_validator(mode="after")
    def validate_payload(self):
        if self.reason is None and self.is_active is None:
            raise ValueError("At least one of reason or is_active must be provided")
        return self


class MonitoredUserCountsModel(BaseModel):
    cases_total: int = 0
    cases_open: int = 0
    actions_total: int = 0


class MonitoredUserReadModel(BaseModel):
    id: str
    server_id: str
    reason: str | None = None
    source: str = "manual"
    release_due_at: datetime | None = None
    released_at: datetime | None = None
    release_error: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    user: ModerationActorModel
    added_by: ModerationActorModel
    counts: MonitoredUserCountsModel | None = None


class MonitoredUserCommentCreateModel(BaseModel):
    comment: str = Field(min_length=1, max_length=10000)
    author_user_id: str | None = Field(default=None, pattern=r"^\d*$")

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("comment cannot be empty")
        return cleaned


class MonitoredUserCommentReadModel(BaseModel):
    id: str
    monitored_user_id: str
    comment: str
    created_at: datetime
    author: ModerationActorModel


class MonitoredUserStatusEventReadModel(BaseModel):
    id: str
    monitored_user_id: str
    from_is_active: bool | None = None
    to_is_active: bool
    changed_at: datetime
    changed_by: ModerationActorModel


class UserCaseSummaryModel(BaseModel):
    id: str
    title: str
    status: CaseStatus
    created_at: datetime


class UserActionSummaryModel(BaseModel):
    id: str
    action_type: str
    reason: str
    created_at: datetime
    moderator: ModerationActorModel


class MonitoredUserDetailsModel(MonitoredUserReadModel):
    related_cases: list[UserCaseSummaryModel] = Field(default_factory=list)
    recent_actions: list[UserActionSummaryModel] = Field(default_factory=list)
    counts: MonitoredUserCountsModel = Field(default_factory=MonitoredUserCountsModel)
    comment_count: int = 0


class MonitoredUserFromCaseModel(BaseModel):
    user_id: str | None = Field(default=None, pattern=r"^\d+$")
    reason: str | None = Field(default=None, max_length=5000)
    added_by_user_id: str | None = Field(default=None, pattern=r"^\d*$")


class MonitoringEventDefaultsModel(BaseModel):
    notify_rejoin: bool = True
    notify_messages: bool = True
    message_threshold: int = Field(default=5, ge=1, le=1000)
    notify_images: bool = True
    notify_voice: bool = True
    notify_threads: bool = True
    notify_commands: bool = True
    notify_ai_interactions: bool = True


class MonitoringEventOverridesModel(BaseModel):
    notify_rejoin: bool | None = None
    notify_messages: bool | None = None
    message_threshold: int | None = Field(default=None, ge=1, le=1000)
    notify_images: bool | None = None
    notify_voice: bool | None = None
    notify_threads: bool | None = None
    notify_commands: bool | None = None
    notify_ai_interactions: bool | None = None


class ServerMonitoringSettingsReadModel(BaseModel):
    server_id: str
    notification_channel_id: str | None = None
    discord_notifications_enabled: bool
    defaults: MonitoringEventDefaultsModel
    auto_monitor_enabled: bool
    auto_monitor_recent_account_days: int
    auto_monitor_no_avatar: bool
    auto_monitor_reason: str
    updated_at: datetime


class ServerMonitoringSettingsUpdateModel(BaseModel):
    notification_channel_id: str | None = Field(default=None, pattern=r"^\d*$")
    discord_notifications_enabled: bool | None = None
    defaults: MonitoringEventDefaultsModel | None = None
    auto_monitor_enabled: bool | None = None
    auto_monitor_recent_account_days: int | None = Field(default=None, ge=1, le=3650)
    auto_monitor_no_avatar: bool | None = None
    auto_monitor_reason: str | None = Field(default=None, min_length=1, max_length=250)


class MonitoredUserNotificationSettingsReadModel(BaseModel):
    monitored_user_id: str
    effective: MonitoringEventDefaultsModel
    overrides: MonitoringEventOverridesModel
    updated_at: datetime | None = None


class MonitoredUserNotificationSettingsUpdateModel(MonitoringEventOverridesModel):
    pass


class MonitoredUserActivityEventReadModel(BaseModel):
    id: str
    monitored_user_id: str
    server_id: str
    user_id: str
    event_type: str
    channel_id: str | None = None
    message_id: str | None = None
    message_content: str | None = None
    metadata: dict = Field(default_factory=dict)
    notification_sent: bool
    occurred_at: datetime
    user: ModerationActorModel | None = None
