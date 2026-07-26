from __future__ import annotations

import re
from typing import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import AIKnowledgeSource, GlobalUser, YouTubeChannelSubscription, utcnow_utc_tz
from src.modules.ai.knowledge import queue_knowledge_index_job


CHANNEL_PROFILE_SOURCE_TYPE = "youtube_channel"
_GENERIC_ALIAS_WORDS = {
    "a",
    "and",
    "channel",
    "of",
    "the",
    "youtube",
    "в",
    "и",
    "канал",
    "на",
    "с",
    "ютуб",
}
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def automatic_channel_aliases(channel: YouTubeChannelSubscription) -> list[str]:
    candidates = [channel.title, channel.handle or ""]
    title_tokens = _meaningful_tokens(channel.title)
    if len(title_tokens) >= 2:
        candidates.append("".join(token[0] for token in title_tokens).upper())
    if channel.handle:
        candidates.append(channel.handle.removeprefix("@"))
    return _unique_text(candidates)


def all_channel_aliases(channel: YouTubeChannelSubscription) -> list[str]:
    return _unique_text([*automatic_channel_aliases(channel), *(channel.aliases or [])])


async def upsert_youtube_channel_profile(
    session: AsyncSession,
    channel: YouTubeChannelSubscription,
) -> AIKnowledgeSource:
    now = utcnow_utc_tz()
    aliases = all_channel_aliases(channel)
    related_user_ids = [str(value) for value in (channel.related_user_ids or []) if str(value).isdigit()]
    related_names = await _related_member_names(session, related_user_ids)
    content_text = _channel_profile_text(
        channel,
        aliases=aliases,
        related_names=related_names,
    )
    metadata = {
        "youtube_channel": {
            "subscription_id": str(channel.id),
            "channel_id": channel.channel_id,
            "handle": channel.handle,
            "aliases": aliases,
            "related_user_ids": related_user_ids,
        }
    }
    source = await _find_channel_profile_source(session, channel)
    if source is None:
        source = AIKnowledgeSource(
            server_id=channel.server_id,
            source_type=CHANNEL_PROFILE_SOURCE_TYPE,
            subject_type="server",
            status="queued",
            visibility="public_answer",
            title=channel.title[:255],
            content_text=content_text,
            source_url=channel.canonical_url,
            metadata_json=metadata,
            created_by_user_id=channel.created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(source)
        await session.flush()
        await queue_knowledge_index_job(
            session,
            server_id=channel.server_id,
            source_id=source.id,
        )
        return source

    changed = any(
        (
            source.title != channel.title[:255],
            source.content_text != content_text,
            source.source_url != channel.canonical_url,
            dict(source.metadata_json or {}) != metadata,
            source.deleted_at is not None,
        )
    )
    if changed:
        source.title = channel.title[:255]
        source.content_text = content_text
        source.source_url = channel.canonical_url
        source.metadata_json = metadata
        source.status = "queued"
        source.deleted_at = None
        source.error_code = None
        source.error_message = None
        source.updated_at = now
        session.add(source)
        await session.flush()
        await queue_knowledge_index_job(
            session,
            server_id=channel.server_id,
            source_id=source.id,
        )
    return source


async def delete_youtube_channel_profile(
    session: AsyncSession,
    channel: YouTubeChannelSubscription,
) -> None:
    source = await _find_channel_profile_source(session, channel)
    if source is None:
        return
    now = utcnow_utc_tz()
    source.deleted_at = now
    source.updated_at = now
    session.add(source)
    await session.flush()


async def ensure_youtube_channel_profile_once(session: AsyncSession) -> bool:
    channels = (
        await session.exec(
            select(YouTubeChannelSubscription).order_by(YouTubeChannelSubscription.created_at)
        )
    ).all()
    if not channels:
        return False
    sources = (
        await session.exec(
            select(AIKnowledgeSource).where(
                AIKnowledgeSource.source_type == CHANNEL_PROFILE_SOURCE_TYPE,
                AIKnowledgeSource.deleted_at.is_(None),
            )
        )
    ).all()
    known_subscription_ids = {
        str(metadata.get("subscription_id"))
        for source in sources
        if isinstance((metadata := dict(source.metadata_json or {}).get("youtube_channel")), dict)
    }
    for channel in channels:
        if str(channel.id) not in known_subscription_ids:
            await upsert_youtube_channel_profile(session, channel)
            return True
    return False


async def _find_channel_profile_source(
    session: AsyncSession,
    channel: YouTubeChannelSubscription,
) -> AIKnowledgeSource | None:
    sources = (
        await session.exec(
            select(AIKnowledgeSource)
            .where(
                AIKnowledgeSource.server_id == channel.server_id,
                AIKnowledgeSource.source_type == CHANNEL_PROFILE_SOURCE_TYPE,
            )
            .order_by(AIKnowledgeSource.updated_at.desc())
        )
    ).all()
    for source in sources:
        metadata = dict(source.metadata_json or {}).get("youtube_channel")
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("subscription_id")) == str(channel.id):
            return source
        if metadata.get("channel_id") == channel.channel_id:
            return source
    return None


async def _related_member_names(session: AsyncSession, user_ids: list[str]) -> list[str]:
    if not user_ids:
        return []
    rows = (
        await session.exec(
            select(GlobalUser).where(GlobalUser.discord_id.in_([int(value) for value in user_ids]))
        )
    ).all()
    return _unique_text([row.username or "" for row in rows])


def _channel_profile_text(
    channel: YouTubeChannelSubscription,
    *,
    aliases: list[str],
    related_names: list[str],
) -> str:
    lines = [
        f"YouTube channel: {channel.title}",
        f"Handle: {channel.handle}" if channel.handle else None,
        f"URL: {channel.canonical_url}",
        f"Known names and aliases: {', '.join(aliases)}" if aliases else None,
        f"Related server members: {', '.join(related_names)}" if related_names else None,
        f"Channel description: {channel.description}" if channel.description else None,
    ]
    return "\n".join(line for line in lines if line)


def _meaningful_tokens(value: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(value.casefold())
        if len(token) > 1 and token not in _GENERIC_ALIAS_WORDS
    ]


def _unique_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
