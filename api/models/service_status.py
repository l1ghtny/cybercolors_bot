from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ComponentState = Literal["healthy", "reconnecting", "retrying", "unavailable", "unknown"]
ComponentId = Literal["gateway", "commands", "moderation_expiry", "birthdays"]


class ServiceComponent(BaseModel):
    id: ComponentId
    state: ComponentState
    reason: str | None = None


class DiscordIncident(BaseModel):
    title: str
    url: str
    status: str


class ServerServiceStatus(BaseModel):
    state: Literal["healthy", "reconnecting", "degraded", "unknown"]
    server_time: datetime
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    components: list[ServiceComponent]
    discord_incident: DiscordIncident | None = None
    discord_status_observed_at: datetime | None = None
