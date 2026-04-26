from datetime import date, datetime, time, timedelta, timezone
import logging
import os
from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.user_profiles import (
    UserActivityChannelCountModel,
    UserActivityLeaderboardItemModel,
    UserActivitySummaryModel,
    UserActivityUpsertModel,
)
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, fetch_guild_channels
from src.db.database import get_session
from src.db.models import GlobalUser, MessageLog, Server, User, UserActivity

activity = APIRouter(prefix="/activity", tags=["activity"])
logger = logging.getLogger("uvicorn")
ACTIVITY_CHANNEL_CACHE_TTL_SECONDS = int(os.getenv("ACTIVITY_CHANNEL_CACHE_TTL_SECONDS", "120"))


@dataclass
class _ActivityChannelCacheEntry:
    channel_ids: set[int]
    expires_at: float


_activity_channels_cache: dict[int, _ActivityChannelCacheEntry] = {}


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _get_cached_activity_channel_ids(server_id: int) -> set[int] | None:
    if ACTIVITY_CHANNEL_CACHE_TTL_SECONDS <= 0:
        return None
    cached = _activity_channels_cache.get(server_id)
    if not cached:
        return None
    if cached.expires_at <= monotonic():
        _activity_channels_cache.pop(server_id, None)
        return None
    return set(cached.channel_ids)


def _store_cached_activity_channel_ids(server_id: int, channel_ids: set[int]) -> None:
    if ACTIVITY_CHANNEL_CACHE_TTL_SECONDS <= 0:
        return
    _activity_channels_cache[server_id] = _ActivityChannelCacheEntry(
        channel_ids=set(channel_ids),
        expires_at=monotonic() + ACTIVITY_CHANNEL_CACHE_TTL_SECONDS,
    )


async def _get_server_rendered_text_channel_ids(server_id: int, refresh: bool = False) -> set[int] | None:
    cached = None if refresh else _get_cached_activity_channel_ids(server_id)
    if cached is not None:
        return cached

    try:
        channels = await fetch_guild_channels(server_id)
    except Exception as exc:
        logger.warning(
            "Failed to fetch server channels for activity filtering (server_id=%s): %s",
            server_id,
            exc,
        )
        return None

    channel_ids = {
        int(channel["id"])
        for channel in channels
        if str(channel.get("id", "")).isdigit() and int(channel.get("type", -1)) in TEXT_CHANNEL_TYPES
    }
    _store_cached_activity_channel_ids(server_id, channel_ids)
    return channel_ids


def _resolve_period_bounds(
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None, datetime | None, datetime | None]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from cannot be greater than date_to",
        )

    period_start = datetime.combine(date_from, time.min) if date_from else None
    period_end_exclusive = datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None
    # UI-friendly inclusive end.
    period_end = (
        period_end_exclusive - timedelta(microseconds=1)
        if period_end_exclusive is not None
        else None
    )
    return period_start, period_end_exclusive, period_start, period_end


def _build_activity_filters(
    server_id: int,
    user_id: int | None = None,
    period_start: datetime | None = None,
    period_end_exclusive: datetime | None = None,
    channel_ids: set[int] | None = None,
) -> list:
    conditions = [MessageLog.server_id == server_id]
    if user_id is not None:
        conditions.append(MessageLog.user_id == user_id)
    if period_start is not None:
        conditions.append(MessageLog.created_at >= period_start)
    if period_end_exclusive is not None:
        conditions.append(MessageLog.created_at < period_end_exclusive)
    if channel_ids is not None:
        conditions.append(MessageLog.channel_id.in_(channel_ids))
    return conditions


async def _get_or_create_server_record(server_id: int, session: AsyncSession) -> Server:
    server = await session.get(Server, server_id)
    if server:
        return server
    server = Server(server_id=server_id, server_name=str(server_id))
    session.add(server)
    await session.flush()
    return server


async def _get_or_create_user_membership(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    username: str | None = None,
    server_nickname: str | None = None,
) -> tuple[GlobalUser, User]:
    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        global_user = GlobalUser(discord_id=user_id, username=username)
        session.add(global_user)
        await session.flush()
    elif username and global_user.username != username:
        global_user.username = username
        session.add(global_user)

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    if not membership:
        membership = User(
            user_id=user_id,
            server_id=server_id,
            server_nickname=server_nickname,
            is_member=True,
        )
        session.add(membership)
        await session.flush()
    else:
        if server_nickname:
            membership.server_nickname = server_nickname
        membership.is_member = True
        session.add(membership)

    return global_user, membership


def _to_activity_summary(item: UserActivity) -> UserActivitySummaryModel:
    channel_id = str(item.channel_id)
    return UserActivitySummaryModel(
        user_id=str(item.user_id),
        server_id=str(item.server_id),
        message_count=item.message_count,
        last_message_at=item.last_message_at,
        channel_id=channel_id,
        channels=[UserActivityChannelCountModel(channel_id=channel_id, message_count=item.message_count)],
    )


async def _fetch_user_channel_counts(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    period_start: datetime | None,
    period_end_exclusive: datetime | None,
    channel_ids: set[int] | None = None,
) -> list[tuple[int, int]]:
    if channel_ids is not None and not channel_ids:
        return []
    conditions = _build_activity_filters(
        server_id=server_id,
        user_id=user_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        channel_ids=channel_ids,
    )
    rows = (
        await session.exec(
            select(
                MessageLog.channel_id,
                func.count().label("message_count"),
            )
            .where(*conditions)
            .group_by(MessageLog.channel_id)
            .order_by(func.count().desc(), MessageLog.channel_id.asc())
        )
    ).all()
    return [(int(channel_id), int(message_count)) for channel_id, message_count in rows]


async def _fetch_user_last_message_metadata(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    period_start: datetime | None,
    period_end_exclusive: datetime | None,
    channel_ids: set[int] | None = None,
) -> tuple[int | None, datetime | None]:
    if channel_ids is not None and not channel_ids:
        return None, None
    conditions = _build_activity_filters(
        server_id=server_id,
        user_id=user_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        channel_ids=channel_ids,
    )
    row = (
        await session.exec(
            select(MessageLog.channel_id, MessageLog.created_at)
            .where(*conditions)
            .order_by(MessageLog.created_at.desc())
            .limit(1)
        )
    ).first()
    if not row:
        return None, None
    channel_id, created_at = row
    return int(channel_id), _as_naive_utc(created_at)


@activity.post(
    "/users/{server_id}/{user_id}",
    response_model=UserActivitySummaryModel,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_user_activity(
    server_id: int,
    user_id: int,
    body: UserActivityUpsertModel,
    session: AsyncSession = Depends(get_session),
):
    await _get_or_create_server_record(server_id, session)
    await _get_or_create_user_membership(
        session=session,
        server_id=server_id,
        user_id=user_id,
        username=body.username,
        server_nickname=body.server_nickname,
    )

    activity_row = await session.get(UserActivity, (user_id, server_id))
    observed_at = body.observed_at or _naive_utcnow()
    channel_id = int(body.channel_id)
    if not activity_row:
        activity_row = UserActivity(
            user_id=user_id,
            server_id=server_id,
            channel_id=channel_id,
            message_count=body.increment,
            last_message_at=observed_at,
        )
    else:
        activity_row.channel_id = channel_id
        activity_row.message_count += body.increment
        if observed_at >= activity_row.last_message_at:
            activity_row.last_message_at = observed_at

    session.add(activity_row)
    await session.flush()
    await session.refresh(activity_row)
    return _to_activity_summary(activity_row)


@activity.get("/users/{server_id}/{user_id}", response_model=UserActivitySummaryModel)
async def get_user_activity(
    server_id: int,
    user_id: int,
    date_from: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD)."),
    date_to: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD)."),
    channels_limit: int = Query(default=20, ge=1, le=100, description="Max channels to include in breakdown."),
    refresh_channels: bool = Query(default=False, description="Bypass server channel cache for this request."),
    session: AsyncSession = Depends(get_session),
):
    period_start, period_end_exclusive, period_start_out, period_end_out = _resolve_period_bounds(
        date_from,
        date_to,
    )
    active_channel_ids = await _get_server_rendered_text_channel_ids(server_id, refresh=refresh_channels)

    # Date-filtered activity is computed from raw message logs.
    if period_start is not None or period_end_exclusive is not None:
        channel_rows = await _fetch_user_channel_counts(
            session=session,
            server_id=server_id,
            user_id=user_id,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
            channel_ids=active_channel_ids,
        )
        latest_channel_id, latest_message_at = await _fetch_user_last_message_metadata(
            session=session,
            server_id=server_id,
            user_id=user_id,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
            channel_ids=active_channel_ids,
        )
        channels = [
            UserActivityChannelCountModel(channel_id=str(channel_id), message_count=message_count)
            for channel_id, message_count in channel_rows[:channels_limit]
        ]
        return UserActivitySummaryModel(
            user_id=str(user_id),
            server_id=str(server_id),
            message_count=sum(message_count for _, message_count in channel_rows),
            last_message_at=latest_message_at,
            channel_id=str(latest_channel_id) if latest_channel_id is not None else None,
            channels=channels,
            period_start=period_start_out,
            period_end=period_end_out,
        )

    channel_rows = await _fetch_user_channel_counts(
        session=session,
        server_id=server_id,
        user_id=user_id,
        period_start=None,
        period_end_exclusive=None,
        channel_ids=active_channel_ids,
    )

    if not channel_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")

    latest_channel_id, latest_message_at = await _fetch_user_last_message_metadata(
        session=session,
        server_id=server_id,
        user_id=user_id,
        period_start=None,
        period_end_exclusive=None,
        channel_ids=active_channel_ids,
    )

    channels = [
        UserActivityChannelCountModel(channel_id=str(channel_id), message_count=message_count)
        for channel_id, message_count in channel_rows[:channels_limit]
    ]

    return UserActivitySummaryModel(
        user_id=str(user_id),
        server_id=str(server_id),
        message_count=sum(message_count for _, message_count in channel_rows),
        last_message_at=latest_message_at,
        channel_id=str(latest_channel_id) if latest_channel_id is not None else None,
        channels=channels,
    )


@activity.get("/{server_id}/leaderboard", response_model=list[UserActivityLeaderboardItemModel])
async def get_server_activity_leaderboard(
    server_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    date_from: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD)."),
    date_to: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD)."),
    channels_limit: int = Query(default=5, ge=1, le=20, description="Max channels per user in breakdown."),
    refresh_channels: bool = Query(default=False, description="Bypass server channel cache for this request."),
    session: AsyncSession = Depends(get_session),
):
    period_start, period_end_exclusive, period_start_out, period_end_out = _resolve_period_bounds(
        date_from,
        date_to,
    )
    active_channel_ids = await _get_server_rendered_text_channel_ids(server_id, refresh=refresh_channels)
    if active_channel_ids is not None and not active_channel_ids:
        return []

    conditions = _build_activity_filters(
        server_id=server_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        channel_ids=active_channel_ids,
    )

    leaderboard_rows = (
        await session.exec(
            select(
                MessageLog.user_id,
                func.count().label("message_count"),
                func.max(MessageLog.created_at).label("last_message_at"),
            )
            .where(*conditions)
            .group_by(MessageLog.user_id)
            .order_by(
                func.count().desc(),
                func.max(MessageLog.created_at).desc(),
                MessageLog.user_id.asc(),
            )
            .limit(limit)
        )
    ).all()
    if not leaderboard_rows:
        return []

    user_ids = [int(user_id) for user_id, _, _ in leaderboard_rows]
    global_user_rows = (
        await session.exec(
            select(GlobalUser.discord_id, GlobalUser.username).where(GlobalUser.discord_id.in_(user_ids))
        )
    ).all()
    global_user_map = {int(discord_id): username for discord_id, username in global_user_rows}

    membership_rows = (
        await session.exec(
            select(User.user_id, User.server_nickname).where(
                User.server_id == server_id,
                User.user_id.in_(user_ids),
            )
        )
    ).all()
    membership_map = {int(user_id): server_nickname for user_id, server_nickname in membership_rows}

    channel_rows = (
        await session.exec(
            select(
                MessageLog.user_id,
                MessageLog.channel_id,
                func.count().label("message_count"),
            )
            .where(*conditions, MessageLog.user_id.in_(user_ids))
            .group_by(MessageLog.user_id, MessageLog.channel_id)
            .order_by(
                MessageLog.user_id.asc(),
                func.count().desc(),
                MessageLog.channel_id.asc(),
            )
        )
    ).all()
    channels_by_user: dict[int, list[UserActivityChannelCountModel]] = {}
    for user_id, channel_id, message_count in channel_rows:
        user_key = int(user_id)
        bucket = channels_by_user.setdefault(user_key, [])
        if len(bucket) >= channels_limit:
            continue
        bucket.append(
            UserActivityChannelCountModel(
                channel_id=str(channel_id),
                message_count=int(message_count),
            )
        )

    result: list[UserActivityLeaderboardItemModel] = []
    for user_id, message_count, last_message_at in leaderboard_rows:
        user_key = int(user_id)
        username = global_user_map.get(user_key)
        server_nickname = membership_map.get(user_key)
        display_name = server_nickname or username or str(user_key)
        result.append(
            UserActivityLeaderboardItemModel(
                user_id=str(user_key),
                username=username,
                server_nickname=server_nickname,
                display_name=display_name,
                message_count=int(message_count),
                last_message_at=_as_naive_utc(last_message_at) or _naive_utcnow(),
                channels=channels_by_user.get(user_key, []),
                period_start=period_start_out,
                period_end=period_end_out,
            )
        )
    return result
