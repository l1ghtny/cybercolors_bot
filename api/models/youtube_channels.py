from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


YouTubeChannelSubscriptionStatus = Literal["enabled", "disabled", "error"]


class YouTubeChannelSubscriptionCreateModel(BaseModel):
    channel_url: str = Field(min_length=1, max_length=4000)
    auto_index_new_videos: bool = False

    @field_validator("channel_url")
    @classmethod
    def normalize_channel_url(cls, value: str) -> str:
        return value.strip()


class YouTubeChannelSubscriptionUpdateModel(BaseModel):
    status: Literal["enabled", "disabled"] | None = None
    auto_index_new_videos: bool | None = None


class YouTubeChannelSubscriptionReadModel(BaseModel):
    id: str
    server_id: str
    channel_id: str
    handle: str | None = None
    canonical_url: str
    title: str
    description: str | None = None
    thumbnail_url: str | None = None
    status: str
    auto_index_new_videos: bool
    video_count: int = 0
    linked_video_count: int = 0
    last_synced_at: datetime | None = None
    next_sync_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class YouTubeChannelSubscriptionListModel(BaseModel):
    items: list[YouTubeChannelSubscriptionReadModel] = Field(default_factory=list)


class YouTubeChannelVideoReadModel(BaseModel):
    id: str
    video_id: str
    title: str
    description: str | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    availability: str
    captions_available: bool | None = None
    knowledge_source_id: str | None = None
    knowledge_source_status: str | None = None
    discovered_at: datetime
    updated_at: datetime


class YouTubeChannelVideoListModel(BaseModel):
    items: list[YouTubeChannelVideoReadModel] = Field(default_factory=list)


class YouTubeChannelVideoLinkModel(BaseModel):
    knowledge_source_id: UUID | None = None
