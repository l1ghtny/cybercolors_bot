from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

import discord
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import (
    GlobalUser,
    HistoricalActivityImportCursor,
    HistoricalUserActivityDaily,
    Server,
    User,
    utcnow_utc_tz,
)

logger = logging.getLogger(__name__)


@dataclass
class HistoricalActivityImportOptions:
    server_id: int
    channel_ids: set[int] | None = None
    page_size: int = 100
    page_sleep_seconds: float = 0.75
    max_pages_per_channel: int | None = None
    include_threads: bool = True


@dataclass
class HistoricalActivityImportStats:
    channels_seen: int = 0
    channels_completed: int = 0
    pages_scanned: int = 0
    messages_scanned: int = 0
    messages_imported: int = 0
    bot_messages_skipped: int = 0


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _discord_avatar_hash(user: discord.abc.User) -> str | None:
    avatar = getattr(user, "avatar", None)
    return getattr(avatar, "key", None) if avatar else None


def _discord_username(user: discord.abc.User) -> str:
    return getattr(user, "name", None) or str(user.id)


def _channel_type_name(channel: discord.abc.GuildChannel | discord.Thread) -> str:
    return channel.__class__.__name__


async def _ensure_server(session: AsyncSession, guild: discord.Guild) -> None:
    server = await session.get(Server, guild.id)
    icon = str(guild.icon) if guild.icon else None
    if server is None:
        server = Server(server_id=guild.id, server_name=guild.name, icon=icon, bot_active=True)
    else:
        server.server_name = guild.name
        server.icon = icon
        server.bot_active = True
    session.add(server)


async def _ensure_user(session: AsyncSession, guild: discord.Guild, user: discord.abc.User) -> None:
    global_user = await session.get(GlobalUser, user.id)
    username = _discord_username(user)
    avatar_hash = _discord_avatar_hash(user)
    created_at = getattr(user, "created_at", None)
    if global_user is None:
        global_user = GlobalUser(
            discord_id=user.id,
            username=username,
            avatar_hash=avatar_hash,
            joined_discord=created_at,
        )
    else:
        global_user.username = username
        global_user.avatar_hash = avatar_hash
        if created_at is not None and global_user.joined_discord is None:
            global_user.joined_discord = created_at
    session.add(global_user)

    member = guild.get_member(user.id)
    membership = (
        await session.exec(
            select(User).where(User.server_id == guild.id, User.user_id == user.id)
        )
    ).first()
    if membership is None:
        membership = User(
            server_id=guild.id,
            user_id=user.id,
            server_nickname=member.display_name if member else None,
            joined_server_at=_as_naive_utc(member.joined_at) if member and member.joined_at else None,
            is_member=member is not None,
        )
    elif member is not None:
        membership.server_nickname = member.display_name
        membership.joined_server_at = _as_naive_utc(member.joined_at) if member.joined_at else membership.joined_server_at
        membership.left_server_at = None
        membership.flagged_absent_at = None
        membership.is_member = True
    session.add(membership)


async def _get_or_create_cursor(
    session: AsyncSession,
    guild_id: int,
    channel: discord.abc.GuildChannel | discord.Thread,
) -> HistoricalActivityImportCursor:
    cursor = await session.get(HistoricalActivityImportCursor, (guild_id, channel.id))
    if cursor is None:
        cursor = HistoricalActivityImportCursor(
            server_id=guild_id,
            channel_id=channel.id,
            channel_name=getattr(channel, "name", str(channel.id)),
            channel_type=_channel_type_name(channel),
        )
    else:
        cursor.channel_name = getattr(channel, "name", str(channel.id))
        cursor.channel_type = _channel_type_name(channel)
    session.add(cursor)
    return cursor


async def _upsert_daily_counts(
    session: AsyncSession,
    guild: discord.Guild,
    counts: dict[tuple[int, int, date], tuple[int, datetime]],
) -> None:
    if not counts:
        return
    now = utcnow_utc_tz()
    rows = [
        {
            "server_id": guild.id,
            "user_id": user_id,
            "channel_id": channel_id,
            "activity_date": activity_date,
            "message_count": message_count,
            "last_message_at": last_message_at,
            "created_at": now,
            "updated_at": now,
        }
        for (user_id, channel_id, activity_date), (message_count, last_message_at) in counts.items()
    ]
    insert_stmt = pg_insert(HistoricalUserActivityDaily).values(rows)
    excluded = insert_stmt.excluded
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["server_id", "user_id", "channel_id", "activity_date"],
        set_={
            "message_count": HistoricalUserActivityDaily.message_count + excluded.message_count,
            "last_message_at": sa.func.greatest(HistoricalUserActivityDaily.last_message_at, excluded.last_message_at),
            "updated_at": now,
        },
    )
    await session.execute(stmt)


async def _visible_history_channels(
    guild: discord.Guild,
    include_threads: bool,
) -> list[discord.abc.GuildChannel | discord.Thread]:
    channels: list[discord.abc.GuildChannel | discord.Thread] = list(guild.text_channels)
    if not include_threads:
        return channels

    seen_thread_ids: set[int] = set()
    for thread in guild.threads:
        seen_thread_ids.add(thread.id)
        channels.append(thread)

    parents: Iterable[discord.abc.GuildChannel] = [*guild.text_channels, *getattr(guild, "forum_channels", [])]
    for parent in parents:
        archived_threads = getattr(parent, "archived_threads", None)
        if archived_threads is None:
            continue
        try:
            async for thread in parent.archived_threads(limit=None):
                if thread.id in seen_thread_ids:
                    continue
                seen_thread_ids.add(thread.id)
                channels.append(thread)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Skipping archived threads for %s (%s): %s", getattr(parent, "name", parent.id), parent.id, exc)
    return channels


async def _import_channel_page(
    session: AsyncSession,
    guild: discord.Guild,
    channel: discord.abc.GuildChannel | discord.Thread,
    cursor: HistoricalActivityImportCursor,
    page_size: int,
) -> tuple[int, int, int, int]:
    before = discord.Object(id=cursor.last_before_message_id) if cursor.last_before_message_id else None
    messages = [message async for message in channel.history(limit=page_size, before=before, oldest_first=False)]
    if not messages:
        cursor.reached_start = True
        cursor.last_error = None
        cursor.updated_at = utcnow_utc_tz()
        session.add(cursor)
        return 0, 0, 0, 0

    counts: dict[tuple[int, int, date], tuple[int, datetime]] = {}
    seen_users: dict[int, discord.abc.User] = {}
    imported = 0
    skipped_bots = 0
    for message in messages:
        author = message.author
        if getattr(author, "bot", False):
            skipped_bots += 1
            continue
        created_at = _as_naive_utc(message.created_at)
        if created_at is None:
            continue
        seen_users[author.id] = author
        key = (author.id, channel.id, created_at.date())
        previous_count, previous_last = counts.get(key, (0, created_at))
        counts[key] = (previous_count + 1, max(previous_last, created_at))
        imported += 1

    await _ensure_server(session, guild)
    for user in seen_users.values():
        await _ensure_user(session, guild, user)
    await _upsert_daily_counts(session, guild, counts)

    oldest_message = messages[-1]
    newest_message = messages[0]
    cursor.last_before_message_id = oldest_message.id
    cursor.pages_scanned += 1
    cursor.messages_scanned += len(messages)
    cursor.messages_imported += imported
    oldest_created_at = _as_naive_utc(oldest_message.created_at)
    newest_created_at = _as_naive_utc(newest_message.created_at)
    if oldest_created_at is not None:
        cursor.oldest_message_at = (
            oldest_created_at
            if cursor.oldest_message_at is None
            else min(cursor.oldest_message_at, oldest_created_at)
        )
    if newest_created_at is not None:
        cursor.newest_message_at = (
            newest_created_at
            if cursor.newest_message_at is None
            else max(cursor.newest_message_at, newest_created_at)
        )
    cursor.reached_start = len(messages) < page_size
    cursor.last_error = None
    cursor.updated_at = utcnow_utc_tz()
    session.add(cursor)
    return 1, len(messages), imported, skipped_bots


async def import_historical_activity(
    client: discord.Client,
    session_factory,
    options: HistoricalActivityImportOptions,
) -> HistoricalActivityImportStats:
    guild = client.get_guild(options.server_id)
    if guild is None:
        guild = await client.fetch_guild(options.server_id)
    if guild is None:
        raise RuntimeError(f"Guild {options.server_id} is not visible to this bot")

    stats = HistoricalActivityImportStats()
    channels = await _visible_history_channels(guild, options.include_threads)
    if options.channel_ids is not None:
        channels = [channel for channel in channels if channel.id in options.channel_ids]
    stats.channels_seen = len(channels)

    async with session_factory() as session:
        await _ensure_server(session, guild)
        await session.commit()

    for channel in channels:
        pages_for_channel = 0
        while True:
            async with session_factory() as session:
                cursor = await _get_or_create_cursor(session, guild.id, channel)
                if cursor.reached_start:
                    stats.channels_completed += 1
                    await session.commit()
                    break
                if options.max_pages_per_channel is not None and pages_for_channel >= options.max_pages_per_channel:
                    await session.commit()
                    break
                try:
                    pages, scanned, imported, skipped_bots = await _import_channel_page(
                        session=session,
                        guild=guild,
                        channel=channel,
                        cursor=cursor,
                        page_size=options.page_size,
                    )
                except (discord.Forbidden, discord.HTTPException) as exc:
                    cursor.last_error = str(exc)
                    cursor.updated_at = utcnow_utc_tz()
                    session.add(cursor)
                    await session.commit()
                    logger.warning("Failed importing %s (%s): %s", getattr(channel, "name", channel.id), channel.id, exc)
                    break
                await session.commit()

            if pages == 0:
                stats.channels_completed += 1
                break
            pages_for_channel += pages
            stats.pages_scanned += pages
            stats.messages_scanned += scanned
            stats.messages_imported += imported
            stats.bot_messages_skipped += skipped_bots
            logger.info(
                "Imported page from %s (%s): scanned=%s imported=%s skipped_bots=%s",
                getattr(channel, "name", channel.id),
                channel.id,
                scanned,
                imported,
                skipped_bots,
            )
            if options.page_sleep_seconds > 0:
                await asyncio.sleep(options.page_sleep_seconds)

    return stats
