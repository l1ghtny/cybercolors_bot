from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


YouTubeChannelSubscriptionStatus = Literal["enabled", "disabled", "error"]


class YouTubeChannelSubscriptionCreateModel(BaseModel):
    channel_url: str = Field(min_length=1, max_length=4000)
    auto_index_new_videos: bool = False
    aliases: list[str] = Field(default_factory=list, max_length=20)
    related_user_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("channel_url")
    @classmethod
    def normalize_channel_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str]) -> list[str]:
        return _normalize_aliases(values)

    @field_validator("related_user_ids")
    @classmethod
    def normalize_related_user_ids(cls, values: list[str]) -> list[str]:
        return _normalize_user_ids(values)


class YouTubeChannelSubscriptionUpdateModel(BaseModel):
    status: Literal["enabled", "disabled"] | None = None
    auto_index_new_videos: bool | None = None
    aliases: list[str] | None = Field(default=None, max_length=20)
    related_user_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _normalize_aliases(values)

    @field_validator("related_user_ids")
    @classmethod
    def normalize_related_user_ids(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _normalize_user_ids(values)


class YouTubeChannelSubscriptionReadModel(BaseModel):
    id: str
    server_id: str
    channel_id: str
    handle: str | None = None
    canonical_url: str
    title: str
    description: str | None = None
    thumbnail_url: str | None = None
    aliases: list[str] = Field(default_factory=list)
    related_user_ids: list[str] = Field(default_factory=list)
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


def _normalize_aliases(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        alias = " ".join(value.split()).strip()[:100]
        key = alias.casefold()
        if alias and key not in seen:
            seen.add(key)
            normalized.append(alias)
    return normalized


def _normalize_user_ids(values: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(str(value).strip() for value in values))
    if any(not value.isdigit() for value in normalized):
        raise ValueError("related_user_ids must contain Discord user IDs")
    return normalized
