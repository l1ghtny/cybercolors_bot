from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import AIKnowledgeSource, YouTubeChannelVideo, utcnow_utc_tz
from src.modules.ai.youtube_urls import YouTubeUrlError, normalize_youtube_video_url


def youtube_video_id_for_source(source: AIKnowledgeSource) -> str | None:
    metadata = dict(source.metadata_json or {})
    for key in ("import", "youtube"):
        section = metadata.get(key)
        if isinstance(section, dict) and isinstance(section.get("video_id"), str):
            return section["video_id"]
    if source.source_url:
        try:
            return normalize_youtube_video_url(source.source_url).video_id
        except YouTubeUrlError:
            return None
    return None


async def link_youtube_source_to_channel_video(
    session: AsyncSession,
    source: AIKnowledgeSource,
) -> YouTubeChannelVideo | None:
    if source.source_type != "youtube" or source.deleted_at is not None:
        return None
    video_id = youtube_video_id_for_source(source)
    if not video_id:
        return None
    video = (
        await session.exec(
            select(YouTubeChannelVideo)
            .where(
                YouTubeChannelVideo.server_id == source.server_id,
                YouTubeChannelVideo.video_id == video_id,
            )
            .order_by(YouTubeChannelVideo.discovered_at)
        )
    ).first()
    if video is None:
        return None
    if video.knowledge_source_id != source.id:
        video.knowledge_source_id = source.id
        video.updated_at = utcnow_utc_tz()
        session.add(video)
        await session.flush()
    return video
