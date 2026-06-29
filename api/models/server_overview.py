from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from api.models.moderation_cases import ModerationActorModel


class ServerOverviewStatsModel(BaseModel):
    moderation_actions_today: int = 0
    moderation_actions_total: int = 0
    open_cases: int = 0
    active_mutes: int = 0
    active_monitored_users: int = 0
    deleted_messages_today: int = 0
    replies_count: int = 0
    active_rules_count: int = 0
    birthdays_count: int = 0
    messages_today: int = 0
    active_users_today: int = 0
    last_message_at: datetime | None = None


class ServerOverviewSetupModel(BaseModel):
    mute_role_configured: bool = False
    mod_log_channel_configured: bool = False
    birthday_channel_configured: bool = False
    birthday_role_configured: bool = False
    verified_role_configured: bool = False
    lockdown_enabled: bool = False
    locale_code: str = "en"


class ServerOverviewModel(BaseModel):
    server_id: str
    generated_at: datetime
    stats: ServerOverviewStatsModel
    setup: ServerOverviewSetupModel


class ServerTimelineEventModel(BaseModel):
    id: str
    server_id: str
    event_type: str
    entity_type: str
    entity_id: str
    occurred_at: datetime
    title: str
    description: str | None = None
    actor: ModerationActorModel | None = None
    target: ModerationActorModel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServerTimelineModel(BaseModel):
    server_id: str
    generated_at: datetime
    events: list[ServerTimelineEventModel] = Field(default_factory=list)