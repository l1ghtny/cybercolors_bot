from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Literal

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import AIKnowledgeSource, GlobalUser, YouTubeChannelSubscription, YouTubeChannelVideo
from src.modules.ai.knowledge import search_server_knowledge
from src.modules.ai.youtube_channel_profiles import CHANNEL_PROFILE_SOURCE_TYPE, all_channel_aliases


MAX_CHANNEL_CATALOG_RESULTS = 20
logger = logging.getLogger(__name__)
YouTubeKnowledgeMode = Literal[
    "list_channels",
    "channel_info",
    "latest_videos",
    "search_videos",
    "search_transcripts",
]
_GENERIC_QUERY_WORDS = {
    "a",
    "about",
    "channel",
    "of",
    "the",
    "video",
    "videos",
    "youtube",
    "видео",
    "канал",
    "канале",
    "канала",
    "про",
    "ютуб",
    "ютубе",
}
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


async def search_youtube_channel_catalog(
    session: AsyncSession,
    *,
    server_id: int,
    channel_query: str | None = None,
    video_query: str | None = None,
    content_query: str | None = None,
    mode: YouTubeKnowledgeMode = "channel_info",
    limit: int = 10,
) -> dict[str, Any]:
    """Answer channel metadata, catalogue, and linked-transcript retrieval needs."""
    bounded_limit = min(max(int(limit), 1), MAX_CHANNEL_CATALOG_RESULTS)
    normalized_channel_query = _normalized_query(channel_query)
    normalized_video_query = _normalized_query(video_query)
    normalized_content_query = _normalized_query(content_query)

    all_channels = (
        await session.exec(
            select(YouTubeChannelSubscription)
            .where(YouTubeChannelSubscription.server_id == server_id)
            .order_by(YouTubeChannelSubscription.title, YouTubeChannelSubscription.created_at)
        )
    ).all()
    channels = _resolve_channels(all_channels, normalized_channel_query)
    if normalized_channel_query and not channels and all_channels:
        channels = await _resolve_channels_from_index(
            session,
            server_id=server_id,
            channels=all_channels,
            query=normalized_channel_query,
        )
    related_names = await _related_member_names_by_channel(session, channels)
    channel_payload = [
        _channel_payload(channel, related_members=related_names.get(str(channel.id), []))
        for channel in channels
    ]
    result: dict[str, Any] = {
        "channels": channel_payload,
        "videos": [],
        "transcript_matches": [],
    }
    if not channels or mode in {"list_channels", "channel_info"}:
        return result

    channel_ids = [channel.id for channel in channels if channel.id is not None]
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
            YouTubeChannelVideo.availability == "available",
        )
    )
    if mode == "search_videos" and normalized_video_query:
        video_pattern = _like_pattern(normalized_video_query)
        video_statement = video_statement.where(
            or_(
                YouTubeChannelVideo.title.ilike(video_pattern, escape="\\"),
                YouTubeChannelVideo.description.ilike(video_pattern, escape="\\"),
            )
        )
    if mode == "search_transcripts":
        video_statement = video_statement.where(
            YouTubeChannelVideo.knowledge_source_id.is_not(None),
            AIKnowledgeSource.status == "ready",
        ).limit(500)
    else:
        video_statement = video_statement.limit(bounded_limit)
    video_statement = video_statement.order_by(
        YouTubeChannelVideo.published_at.desc().nullslast(),
        YouTubeChannelVideo.discovered_at.desc(),
    )

    rows = (await session.exec(video_statement)).all()
    if mode != "search_transcripts":
        result["videos"] = [
            _video_payload(video, knowledge_source_status=source_status)
            for video, _channel, source_status in rows
        ]
        return result

    source_ids = [
        str(video.knowledge_source_id)
        for video, _channel, _source_status in rows
        if video.knowledge_source_id is not None
    ]
    if not source_ids or not normalized_content_query:
        return result
    matches = await search_server_knowledge(
        session,
        server_id=server_id,
        query=normalized_content_query,
        visibility="public_answer",
        limit=bounded_limit,
        source_ids=source_ids,
    )
    result["transcript_matches"] = [
        {
            "video_title": match["title"],
            "video_url": match["source_url"],
            "excerpt": match["text"],
            "relevance": round(float(match["score"]), 3),
        }
        for match in matches
    ]
    return result


def _resolve_channels(
    channels: list[YouTubeChannelSubscription],
    query: str | None,
) -> list[YouTubeChannelSubscription]:
    if not query:
        return channels
    ranked = sorted(
        ((_channel_match_score(channel, query), channel) for channel in channels),
        key=lambda item: item[0],
        reverse=True,
    )
    return [channel for score, channel in ranked if score >= 0.62][:3]


async def _resolve_channels_from_index(
    session: AsyncSession,
    *,
    server_id: int,
    channels: list[YouTubeChannelSubscription],
    query: str,
) -> list[YouTubeChannelSubscription]:
    """Use indexed channel profiles when aliases alone cannot resolve a request."""
    sources = (
        await session.exec(
            select(AIKnowledgeSource).where(
                AIKnowledgeSource.server_id == server_id,
                AIKnowledgeSource.source_type == CHANNEL_PROFILE_SOURCE_TYPE,
                AIKnowledgeSource.deleted_at.is_(None),
            )
        )
    ).all()
    source_ids = [str(source.id) for source in sources if source.id is not None]
    if not source_ids:
        return []
    try:
        matches = await search_server_knowledge(
            session,
            server_id=server_id,
            query=query,
            visibility="public_answer",
            limit=3,
            min_score=0.45,
            source_ids=source_ids,
        )
    except Exception:
        logger.exception("youtube_channel_profile_search_failed server_id=%s", server_id)
        return []

    source_by_id = {str(source.id): source for source in sources if source.id is not None}
    channel_by_id = {str(channel.id): channel for channel in channels if channel.id is not None}
    resolved: list[YouTubeChannelSubscription] = []
    seen: set[str] = set()
    for match in matches:
        source = source_by_id.get(str(match.get("source_id") or ""))
        metadata = (
            dict(source.metadata_json or {}).get("youtube_channel")
            if source is not None
            else None
        )
        subscription_id = str(metadata.get("subscription_id")) if isinstance(metadata, dict) else ""
        channel = channel_by_id.get(subscription_id)
        if channel is not None and subscription_id not in seen:
            seen.add(subscription_id)
            resolved.append(channel)
    return resolved


def _channel_match_score(channel: YouTubeChannelSubscription, query: str) -> float:
    query_normalized = _search_normalized(query)
    query_tokens = _meaningful_tokens(query_normalized)
    best = 0.0
    for candidate in all_channel_aliases(channel):
        candidate_normalized = _search_normalized(candidate)
        if not candidate_normalized:
            continue
        if query_normalized == candidate_normalized:
            return 1.0
        if query_normalized in candidate_normalized or candidate_normalized in query_normalized:
            best = max(best, 0.94)
        best = max(best, SequenceMatcher(None, query_normalized, candidate_normalized).ratio())
        candidate_tokens = _meaningful_tokens(candidate_normalized)
        for query_token in query_tokens:
            for candidate_token in candidate_tokens:
                token_score = SequenceMatcher(None, query_token, candidate_token).ratio()
                if query_token == candidate_token:
                    token_score = 0.98
                best = max(best, token_score)
    return best


def _channel_payload(
    channel: YouTubeChannelSubscription,
    *,
    related_members: list[str],
) -> dict[str, Any]:
    primary_names = {channel.title.casefold(), (channel.handle or "").casefold()}
    known_as = [
        alias
        for alias in all_channel_aliases(channel)
        if alias.casefold() not in primary_names
    ]
    return {
        "name": channel.title,
        "handle": channel.handle,
        "known_as": known_as,
        "related_members": related_members,
        "description": _truncate(channel.description, 1_000),
        "url": channel.canonical_url,
    }


async def _related_member_names_by_channel(
    session: AsyncSession,
    channels: list[YouTubeChannelSubscription],
) -> dict[str, list[str]]:
    user_ids = {
        int(value)
        for channel in channels
        for value in (channel.related_user_ids or [])
        if str(value).isdigit()
    }
    if not user_ids:
        return {}
    users = (
        await session.exec(select(GlobalUser).where(GlobalUser.discord_id.in_(user_ids)))
    ).all()
    name_by_id = {
        str(user.discord_id): user.username
        for user in users
        if user.username
    }
    return {
        str(channel.id): [
            name_by_id[user_id]
            for user_id in (channel.related_user_ids or [])
            if user_id in name_by_id
        ]
        for channel in channels
    }


def _video_payload(
    video: YouTubeChannelVideo,
    *,
    knowledge_source_status: str | None,
) -> dict[str, Any]:
    return {
        "title": video.title,
        "description": _truncate(video.description, 500),
        "url": f"https://www.youtube.com/watch?v={video.video_id}",
        "published_at": _iso_utc(video.published_at),
        "duration_seconds": video.duration_seconds,
        "transcript_available": knowledge_source_status == "ready",
    }


def _normalized_query(value: str | None) -> str | None:
    normalized = " ".join((value or "").split()).strip()
    return normalized[:500] or None


def _search_normalized(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _meaningful_tokens(value: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(value.casefold())
        if token not in _GENERIC_QUERY_WORDS
    ]


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
