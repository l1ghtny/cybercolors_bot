from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import AIKnowledgeSource, YouTubeChannelSubscription, YouTubeChannelVideo


MAX_CHANNEL_CATALOG_RESULTS = 20


async def search_youtube_channel_catalog(
    session: AsyncSession,
    *,
    server_id: int,
    channel_query: str | None = None,
    video_query: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return public channel metadata and recent/matching videos for one server."""
    bounded_limit = min(max(int(limit), 1), MAX_CHANNEL_CATALOG_RESULTS)
    normalized_channel_query = _normalized_query(channel_query)
    normalized_video_query = _normalized_query(video_query)

    channel_statement = (
        select(YouTubeChannelSubscription)
        .where(YouTubeChannelSubscription.server_id == server_id)
        .order_by(YouTubeChannelSubscription.title, YouTubeChannelSubscription.created_at)
    )
    if normalized_channel_query:
        channel_pattern = _like_pattern(normalized_channel_query)
        channel_statement = channel_statement.where(
            or_(
                YouTubeChannelSubscription.title.ilike(channel_pattern, escape="\\"),
                YouTubeChannelSubscription.handle.ilike(channel_pattern, escape="\\"),
                YouTubeChannelSubscription.channel_id.ilike(channel_pattern, escape="\\"),
            )
        )

    channels = (await session.exec(channel_statement)).all()
    channel_ids = [channel.id for channel in channels if channel.id is not None]
    channel_payload = [_channel_payload(channel) for channel in channels]
    if not channel_ids:
        return {
            "channels": channel_payload,
            "videos": [],
            "returned_video_count": 0,
        }

    video_statement = (
        select(
            YouTubeChannelVideo,
            YouTubeChannelSubscription,
            AIKnowledgeSource.status,
        )
        .join(
            YouTubeChannelSubscription,
            YouTubeChannelSubscription.id == YouTubeChannelVideo.subscription_id,
        )
        .outerjoin(
            AIKnowledgeSource,
            AIKnowledgeSource.id == YouTubeChannelVideo.knowledge_source_id,
        )
        .where(
            YouTubeChannelVideo.server_id == server_id,
            YouTubeChannelVideo.subscription_id.in_(channel_ids),
        )
    )
    if normalized_video_query:
        video_pattern = _like_pattern(normalized_video_query)
        video_statement = video_statement.where(
            or_(
                YouTubeChannelVideo.title.ilike(video_pattern, escape="\\"),
                YouTubeChannelVideo.description.ilike(video_pattern, escape="\\"),
                YouTubeChannelVideo.video_id.ilike(video_pattern, escape="\\"),
            )
        )
    video_statement = video_statement.order_by(
        YouTubeChannelVideo.published_at.desc().nullslast(),
        YouTubeChannelVideo.discovered_at.desc(),
    ).limit(bounded_limit)

    rows = (await session.exec(video_statement)).all()
    videos = [
        _video_payload(video, channel=channel, knowledge_source_status=source_status)
        for video, channel, source_status in rows
    ]
    return {
        "channels": channel_payload,
        "videos": videos,
        "returned_video_count": len(videos),
    }


def _channel_payload(channel: YouTubeChannelSubscription) -> dict[str, Any]:
    return {
        "channel_id": channel.channel_id,
        "title": channel.title,
        "handle": channel.handle,
        "description": _truncate(channel.description, 1_000),
        "url": channel.canonical_url,
        "status": channel.status,
        "last_synced_at": _iso_utc(channel.last_synced_at),
    }


def _video_payload(
    video: YouTubeChannelVideo,
    *,
    channel: YouTubeChannelSubscription,
    knowledge_source_status: str | None,
) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "description": _truncate(video.description, 500),
        "url": f"https://www.youtube.com/watch?v={video.video_id}",
        "published_at": _iso_utc(video.published_at),
        "duration_seconds": video.duration_seconds,
        "availability": video.availability,
        "channel_id": channel.channel_id,
        "channel_title": channel.title,
        "channel_handle": channel.handle,
        "knowledge_source_id": str(video.knowledge_source_id) if video.knowledge_source_id else None,
        "transcript_status": knowledge_source_status,
        "has_indexed_transcript": knowledge_source_status == "ready",
    }


def _normalized_query(value: str | None) -> str | None:
    normalized = " ".join((value or "").split()).strip()
    return normalized[:200] or None


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _truncate(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
