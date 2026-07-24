import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import (
    AIKnowledgeSource,
    YouTubeChannelSubscription,
    YouTubeChannelVideo,
    utcnow_utc_tz,
)
from src.modules.ai.knowledge import queue_knowledge_index_job
from src.modules.ai.youtube_data import (
    YouTubeChannel,
    YouTubeDataClient,
    YouTubeDataError,
    YouTubeVideo,
)
from src.modules.ai.youtube_urls import YouTubeUrlError, normalize_youtube_video_url


logger = logging.getLogger(__name__)

YOUTUBE_CHANNEL_SYNC_INTERVAL_SECONDS = int(
    os.getenv("AI_YOUTUBE_CHANNEL_SYNC_INTERVAL_SECONDS") or str(6 * 60 * 60)
)
YOUTUBE_CHANNEL_RETRY_INTERVAL_SECONDS = int(
    os.getenv("AI_YOUTUBE_CHANNEL_RETRY_INTERVAL_SECONDS") or str(30 * 60)
)
YOUTUBE_CHANNEL_MAX_VIDEOS = int(os.getenv("AI_YOUTUBE_CHANNEL_MAX_VIDEOS") or "500")


async def sync_youtube_channel_subscription(
    session: AsyncSession,
    subscription: YouTubeChannelSubscription,
    *,
    client: YouTubeDataClient | None = None,
    resolved_channel: YouTubeChannel | None = None,
    auto_index_new: bool = True,
) -> bool:
    now = utcnow_utc_tz()
    was_disabled = subscription.status == "disabled"
    try:
        active_client = client or YouTubeDataClient()
        channel = resolved_channel or await asyncio.to_thread(
            active_client.resolve_channel,
            subscription.canonical_url,
        )
        videos = await asyncio.to_thread(
            active_client.list_uploads,
            channel,
            max_videos=max(YOUTUBE_CHANNEL_MAX_VIDEOS, 1),
        )
    except YouTubeDataError as exc:
        subscription.status = "disabled" if was_disabled else "error"
        subscription.error_code = exc.code
        subscription.error_message = exc.safe_message
        retry_seconds = (
            YOUTUBE_CHANNEL_RETRY_INTERVAL_SECONDS
            if exc.retryable
            else YOUTUBE_CHANNEL_SYNC_INTERVAL_SECONDS
        )
        subscription.next_sync_at = now + timedelta(seconds=max(retry_seconds, 60))
        subscription.updated_at = now
        session.add(subscription)
        await session.flush()
        logger.warning(
            "youtube_channel_sync_failed subscription_id=%s channel_id=%s error_code=%s retryable=%s",
            subscription.id,
            subscription.channel_id,
            exc.code,
            exc.retryable,
        )
        return False

    _apply_channel_metadata(subscription, channel)
    existing_rows = (
        await session.exec(
            select(YouTubeChannelVideo).where(
                YouTubeChannelVideo.subscription_id == subscription.id
            )
        )
    ).all()
    existing_by_video_id = {row.video_id: row for row in existing_rows}
    source_by_video_id = await _knowledge_sources_by_video_id(session, server_id=subscription.server_id)

    new_rows: list[YouTubeChannelVideo] = []
    for video in videos:
        row = existing_by_video_id.get(video.video_id)
        if row is None:
            row = YouTubeChannelVideo(
                subscription_id=subscription.id,
                server_id=subscription.server_id,
                video_id=video.video_id,
                title=video.title[:500],
                discovered_at=now,
                updated_at=now,
            )
            new_rows.append(row)
        _apply_video_metadata(row, video, now=now)
        linked_source = source_by_video_id.get(video.video_id)
        if linked_source is not None:
            row.knowledge_source_id = linked_source.id
        session.add(row)

    await session.flush()

    if auto_index_new and subscription.auto_index_new_videos:
        for row in new_rows:
            if row.knowledge_source_id is not None or row.availability != "available":
                continue
            source = await _create_video_knowledge_source(session, subscription=subscription, video=row)
            row.knowledge_source_id = source.id
            session.add(row)

    subscription.status = "disabled" if was_disabled else "enabled"
    subscription.last_synced_at = now
    subscription.next_sync_at = now + timedelta(seconds=max(YOUTUBE_CHANNEL_SYNC_INTERVAL_SECONDS, 60))
    subscription.error_code = None
    subscription.error_message = None
    subscription.updated_at = now
    session.add(subscription)
    await session.flush()
    logger.info(
        "youtube_channel_sync_completed subscription_id=%s channel_id=%s videos=%s new_videos=%s",
        subscription.id,
        subscription.channel_id,
        len(videos),
        len(new_rows),
    )
    return True


async def sync_due_youtube_channel_once(
    session: AsyncSession,
    *,
    client: YouTubeDataClient | None = None,
) -> bool:
    now = utcnow_utc_tz()
    subscription = (
        await session.exec(
            select(YouTubeChannelSubscription)
            .where(
                YouTubeChannelSubscription.status.in_(("enabled", "error")),
                (
                    YouTubeChannelSubscription.next_sync_at.is_(None)
                    | (YouTubeChannelSubscription.next_sync_at <= now)
                ),
            )
            .order_by(
                YouTubeChannelSubscription.next_sync_at,
                YouTubeChannelSubscription.created_at,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).first()
    if subscription is None:
        return False
    await sync_youtube_channel_subscription(session, subscription, client=client)
    return True


def _apply_channel_metadata(
    subscription: YouTubeChannelSubscription,
    channel: YouTubeChannel,
) -> None:
    subscription.channel_id = channel.channel_id
    subscription.handle = channel.handle
    subscription.canonical_url = channel.canonical_url
    subscription.title = channel.title[:255]
    subscription.description = channel.description or None
    subscription.thumbnail_url = channel.thumbnail_url
    subscription.uploads_playlist_id = channel.uploads_playlist_id


def _apply_video_metadata(
    row: YouTubeChannelVideo,
    video: YouTubeVideo,
    *,
    now: datetime,
) -> None:
    row.title = video.title[:500]
    row.description = video.description or None
    row.published_at = _parse_provider_datetime(video.published_at)
    row.duration_seconds = video.duration_seconds
    row.thumbnail_url = video.thumbnail_url
    row.availability = video.availability
    row.captions_available = video.captions_available
    row.updated_at = now


async def _knowledge_sources_by_video_id(
    session: AsyncSession,
    *,
    server_id: int,
) -> dict[str, AIKnowledgeSource]:
    sources = (
        await session.exec(
            select(AIKnowledgeSource)
            .where(
                AIKnowledgeSource.server_id == server_id,
                AIKnowledgeSource.source_type == "youtube",
                AIKnowledgeSource.deleted_at.is_(None),
            )
            .order_by(AIKnowledgeSource.updated_at.desc())
        )
    ).all()
    by_video_id: dict[str, AIKnowledgeSource] = {}
    for source in sources:
        metadata = dict(source.metadata_json or {})
        import_metadata = metadata.get("import")
        youtube_metadata = metadata.get("youtube")
        video_id = None
        if isinstance(import_metadata, dict):
            video_id = import_metadata.get("video_id")
        if not video_id and isinstance(youtube_metadata, dict):
            video_id = youtube_metadata.get("video_id")
        if not video_id and source.source_url:
            try:
                video_id = normalize_youtube_video_url(source.source_url).video_id
            except YouTubeUrlError:
                continue
        if isinstance(video_id, str) and video_id:
            by_video_id.setdefault(video_id, source)
    return by_video_id


async def _create_video_knowledge_source(
    session: AsyncSession,
    *,
    subscription: YouTubeChannelSubscription,
    video: YouTubeChannelVideo,
) -> AIKnowledgeSource:
    now = utcnow_utc_tz()
    source = AIKnowledgeSource(
        server_id=subscription.server_id,
        source_type="youtube",
        subject_type="server",
        status="queued",
        visibility="public_answer",
        title=video.title[:255],
        source_url=f"https://www.youtube.com/watch?v={video.video_id}",
        metadata_json={
            "youtube": {
                "channel_subscription_id": str(subscription.id),
                "channel_id": subscription.channel_id,
                "video_id": video.video_id,
            }
        },
        created_by_user_id=subscription.created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(source)
    await session.flush()
    await queue_knowledge_index_job(
        session,
        server_id=subscription.server_id,
        source_id=source.id,
    )
    return source


def _parse_provider_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
