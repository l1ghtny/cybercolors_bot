import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
import logging
import os
from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.server_access import require_server_dashboard_access
from api.models.user_profiles import (
    UserActivityChannelCountModel,
    UserActivityLeaderboardItemModel,
    UserActivitySummaryModel,
    UserActivityUpsertModel,
    UserActivityWarningModel,
)
from api.services.discord_guilds import TEXT_CHANNEL_TYPES, fetch_guild_channels, fetch_guild_member
from src.db.database import get_session
from src.db.models import ActionType, GlobalUser, HistoricalUserActivityDaily, MessageLog, ModerationAction, Server, ServerModerationSettings, User, UserActivity

activity = APIRouter(
    prefix="/activity",
    tags=["activity"],
    dependencies=[Depends(require_server_dashboard_access)],
)
logger = logging.getLogger("uvicorn")
ACTIVITY_CHANNEL_CACHE_TTL_SECONDS = int(os.getenv("ACTIVITY_CHANNEL_CACHE_TTL_SECONDS", "120"))
ACTIVITY_MEMBER_ROLES_CACHE_TTL_SECONDS = int(os.getenv("ACTIVITY_MEMBER_ROLES_CACHE_TTL_SECONDS", "60"))


@dataclass
class _ActivityChannelCacheEntry:
    channel_ids: set[int]
    expires_at: float


@dataclass
class _ActivityMemberRolesCacheEntry:
    role_ids: set[int]
    expires_at: float


_activity_channels_cache: dict[int, _ActivityChannelCacheEntry] = {}
_activity_member_roles_cache: dict[tuple[int, int], _ActivityMemberRolesCacheEntry] = {}
_activity_member_roles_locks: dict[tuple[int, int], asyncio.Lock] = {}
_activity_member_roles_locks_guard = asyncio.Lock()


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


async def _get_activity_member_roles_lock(server_id: int, user_id: int) -> asyncio.Lock:
    key = (server_id, user_id)
    async with _activity_member_roles_locks_guard:
        lock = _activity_member_roles_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _activity_member_roles_locks[key] = lock
        return lock


def _get_cached_activity_member_role_ids(server_id: int, user_id: int) -> set[int] | None:
    if ACTIVITY_MEMBER_ROLES_CACHE_TTL_SECONDS <= 0:
        return None
    cached = _activity_member_roles_cache.get((server_id, user_id))
    if not cached:
        return None
    if cached.expires_at <= monotonic():
        _activity_member_roles_cache.pop((server_id, user_id), None)
        return None
    return set(cached.role_ids)


def _store_cached_activity_member_role_ids(server_id: int, user_id: int, role_ids: set[int]) -> None:
    if ACTIVITY_MEMBER_ROLES_CACHE_TTL_SECONDS <= 0:
        return
    _activity_member_roles_cache[(server_id, user_id)] = _ActivityMemberRolesCacheEntry(
        role_ids=set(role_ids),
        expires_at=monotonic() + ACTIVITY_MEMBER_ROLES_CACHE_TTL_SECONDS,
    )


async def _get_member_role_ids_for_activity(
    server_id: int,
    user_id: int,
    refresh: bool = False,
) -> set[int] | None:
    cached = None if refresh else _get_cached_activity_member_role_ids(server_id, user_id)
    if cached is not None:
        return cached

    roles_lock = await _get_activity_member_roles_lock(server_id=server_id, user_id=user_id)
    async with roles_lock:
        cached = None if refresh else _get_cached_activity_member_role_ids(server_id, user_id)
        if cached is not None:
            return cached
        try:
            member_payload = await fetch_guild_member(server_id=server_id, user_id=user_id)
        except Exception as exc:
            logger.warning(
                "Failed to fetch guild member roles for activity filtering (server_id=%s, user_id=%s): %s",
                server_id,
                user_id,
                exc,
            )
            return None

        if not member_payload:
            role_ids: set[int] = set()
        else:
            role_ids = {
                int(role_id)
                for role_id in member_payload.get("roles", [])
                if str(role_id).isdigit()
            }
        _store_cached_activity_member_role_ids(server_id=server_id, user_id=user_id, role_ids=role_ids)
        return role_ids


def _parse_id_set_filter(raw_values: list[str] | None, parameter_name: str) -> set[int] | None:
    if raw_values is None:
        return None

    parsed: set[int] = set()
    invalid: list[str] = []
    for raw_value in raw_values:
        for token in str(raw_value).split(","):
            value = token.strip()
            if not value:
                continue
            if not value.isdigit():
                invalid.append(value)
                continue
            parsed.add(int(value))

    if invalid:
        sample = ", ".join(invalid[:5])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{parameter_name} must contain only Discord numeric IDs. Invalid values: {sample}",
        )
    return parsed or None


def _intersect_optional_sets(first: set[int] | None, second: set[int] | None) -> set[int] | None:
    if first is None:
        return second
    if second is None:
        return first
    return first.intersection(second)


async def _fetch_server_activity_excluded_channel_ids(
    session: AsyncSession,
    server_id: int,
) -> set[int]:
    settings = await session.get(ServerModerationSettings, server_id)
    if not settings or not settings.activity_excluded_channel_ids:
        return set()
    return {
        int(channel_id)
        for channel_id in settings.activity_excluded_channel_ids
        if str(channel_id).isdigit()
    }


def _set_activity_leaderboard_meta_headers(
    response: Response,
    server_excluded_channel_ids: set[int],
    server_excludes_applied: bool,
) -> None:
    response.headers["X-Activity-Server-Excludes"] = json.dumps(
        [str(channel_id) for channel_id in sorted(server_excluded_channel_ids)]
    )
    response.headers["X-Activity-Server-Excludes-Applied"] = "true" if server_excludes_applied else "false"


def _resolve_effective_activity_excluded_channel_ids(
    query_excluded_channel_ids: set[int] | None,
    server_excluded_channel_ids: set[int],
    include_channel_ids: set[int] | None,
    ignore_server_excludes: bool,
) -> tuple[set[int] | None, bool]:
    server_excludes_applied = (
        bool(server_excluded_channel_ids)
        and include_channel_ids is None
        and not ignore_server_excludes
    )
    effective_excluded_channel_ids = set(query_excluded_channel_ids or set())
    if server_excludes_applied:
        effective_excluded_channel_ids.update(server_excluded_channel_ids)
    return effective_excluded_channel_ids or None, server_excludes_applied


def _matches_role_filters(
    user_id: int,
    user_role_ids: set[int] | None,
    include_user_ids: set[int] | None,
    exclude_user_ids: set[int] | None,
    include_role_ids: set[int] | None,
    exclude_role_ids: set[int] | None,
) -> bool:
    if exclude_user_ids and user_id in exclude_user_ids:
        return False
    if user_role_ids is None and (include_role_ids or exclude_role_ids):
        return False
    if user_role_ids is not None and exclude_role_ids and user_role_ids.intersection(exclude_role_ids):
        return False

    include_by_user = bool(include_user_ids and user_id in include_user_ids)
    include_by_role = bool(
        include_role_ids
        and user_role_ids is not None
        and user_role_ids.intersection(include_role_ids)
    )
    has_include_filters = bool(include_user_ids or include_role_ids)
    if has_include_filters and not (include_by_user or include_by_role):
        return False
    return True


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
    include_user_ids: set[int] | None = None,
    exclude_user_ids: set[int] | None = None,
    include_channel_ids: set[int] | None = None,
    exclude_channel_ids: set[int] | None = None,
) -> list:
    conditions = [MessageLog.server_id == server_id]
    if user_id is not None:
        conditions.append(MessageLog.user_id == user_id)
    if include_user_ids is not None:
        conditions.append(MessageLog.user_id.in_(include_user_ids))
    if exclude_user_ids:
        conditions.append(MessageLog.user_id.notin_(exclude_user_ids))
    if period_start is not None:
        conditions.append(MessageLog.created_at >= period_start)
    if period_end_exclusive is not None:
        conditions.append(MessageLog.created_at < period_end_exclusive)
    if include_channel_ids is not None:
        conditions.append(MessageLog.channel_id.in_(include_channel_ids))
    if exclude_channel_ids:
        conditions.append(MessageLog.channel_id.notin_(exclude_channel_ids))
    return conditions


def _build_historical_activity_filters(
    server_id: int,
    user_id: int | None = None,
    period_start: datetime | None = None,
    period_end_exclusive: datetime | None = None,
    include_user_ids: set[int] | None = None,
    exclude_user_ids: set[int] | None = None,
    include_channel_ids: set[int] | None = None,
    exclude_channel_ids: set[int] | None = None,
) -> list:
    conditions = [HistoricalUserActivityDaily.server_id == server_id]
    if user_id is not None:
        conditions.append(HistoricalUserActivityDaily.user_id == user_id)
    if include_user_ids is not None:
        conditions.append(HistoricalUserActivityDaily.user_id.in_(include_user_ids))
    if exclude_user_ids:
        conditions.append(HistoricalUserActivityDaily.user_id.notin_(exclude_user_ids))
    if period_start is not None:
        conditions.append(HistoricalUserActivityDaily.activity_date >= period_start.date())
    if period_end_exclusive is not None:
        conditions.append(HistoricalUserActivityDaily.activity_date < period_end_exclusive.date())
    if include_channel_ids is not None:
        conditions.append(HistoricalUserActivityDaily.channel_id.in_(include_channel_ids))
    if exclude_channel_ids:
        conditions.append(HistoricalUserActivityDaily.channel_id.notin_(exclude_channel_ids))
    return conditions


def _merge_channel_counts(*row_sets: list[tuple[int, int]]) -> list[tuple[int, int]]:
    counts: dict[int, int] = {}
    for rows in row_sets:
        for channel_id, message_count in rows:
            counts[int(channel_id)] = counts.get(int(channel_id), 0) + int(message_count)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _activity_sort_timestamp(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    try:
        return value.timestamp()
    except (OSError, OverflowError, ValueError):
        return 0.0


def _merge_leaderboard_rows(*row_sets: list[tuple[int, int, datetime | None]]) -> list[tuple[int, int, datetime | None]]:
    merged: dict[int, tuple[int, datetime | None]] = {}
    for rows in row_sets:
        for user_id, message_count, last_message_at in rows:
            user_key = int(user_id)
            previous_count, previous_last = merged.get(user_key, (0, None))
            normalized_last = _as_naive_utc(last_message_at)
            if previous_last is None or (normalized_last is not None and normalized_last > previous_last):
                latest = normalized_last
            else:
                latest = previous_last
            merged[user_key] = (previous_count + int(message_count), latest)
    return sorted(
        ((user_id, message_count, last_message_at) for user_id, (message_count, last_message_at) in merged.items()),
        key=lambda item: (-item[1], -_activity_sort_timestamp(item[2]), item[0]),
    )


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
    include_channel_ids: set[int] | None = None,
    exclude_channel_ids: set[int] | None = None,
) -> list[tuple[int, int]]:
    if include_channel_ids is not None and not include_channel_ids:
        return []
    live_conditions = _build_activity_filters(
        server_id=server_id,
        user_id=user_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    live_rows = (
        await session.exec(
            select(MessageLog.channel_id, func.count().label("message_count"))
            .where(*live_conditions)
            .group_by(MessageLog.channel_id)
        )
    ).all()
    historical_conditions = _build_historical_activity_filters(
        server_id=server_id,
        user_id=user_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    historical_rows = (
        await session.exec(
            select(
                HistoricalUserActivityDaily.channel_id,
                func.sum(HistoricalUserActivityDaily.message_count).label("message_count"),
            )
            .where(*historical_conditions)
            .group_by(HistoricalUserActivityDaily.channel_id)
        )
    ).all()
    return _merge_channel_counts(
        [(int(channel_id), int(message_count or 0)) for channel_id, message_count in live_rows],
        [(int(channel_id), int(message_count or 0)) for channel_id, message_count in historical_rows],
    )


async def _fetch_user_last_message_metadata(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    period_start: datetime | None,
    period_end_exclusive: datetime | None,
    include_channel_ids: set[int] | None = None,
    exclude_channel_ids: set[int] | None = None,
) -> tuple[int | None, datetime | None]:
    if include_channel_ids is not None and not include_channel_ids:
        return None, None
    live_conditions = _build_activity_filters(
        server_id=server_id,
        user_id=user_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    live_row = (
        await session.exec(
            select(MessageLog.channel_id, MessageLog.created_at)
            .where(*live_conditions)
            .order_by(MessageLog.created_at.desc())
            .limit(1)
        )
    ).first()
    historical_conditions = _build_historical_activity_filters(
        server_id=server_id,
        user_id=user_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    historical_row = (
        await session.exec(
            select(HistoricalUserActivityDaily.channel_id, HistoricalUserActivityDaily.last_message_at)
            .where(*historical_conditions)
            .order_by(HistoricalUserActivityDaily.last_message_at.desc())
            .limit(1)
        )
    ).first()
    candidates: list[tuple[int, datetime]] = []
    if live_row:
        channel_id, created_at = live_row
        normalized = _as_naive_utc(created_at)
        if normalized is not None:
            candidates.append((int(channel_id), normalized))
    if historical_row:
        channel_id, created_at = historical_row
        normalized = _as_naive_utc(created_at)
        if normalized is not None:
            candidates.append((int(channel_id), normalized))
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item[1])


async def _fetch_leaderboard_rows(
    session: AsyncSession,
    server_id: int,
    period_start: datetime | None,
    period_end_exclusive: datetime | None,
    include_user_ids: set[int] | None = None,
    exclude_user_ids: set[int] | None = None,
    include_channel_ids: set[int] | None = None,
    exclude_channel_ids: set[int] | None = None,
) -> list[tuple[int, int, datetime | None]]:
    live_conditions = _build_activity_filters(
        server_id=server_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_user_ids=include_user_ids,
        exclude_user_ids=exclude_user_ids,
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    live_rows = (
        await session.exec(
            select(
                MessageLog.user_id,
                func.count().label("message_count"),
                func.max(MessageLog.created_at).label("last_message_at"),
            )
            .where(*live_conditions)
            .group_by(MessageLog.user_id)
        )
    ).all()
    historical_conditions = _build_historical_activity_filters(
        server_id=server_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_user_ids=include_user_ids,
        exclude_user_ids=exclude_user_ids,
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    historical_rows = (
        await session.exec(
            select(
                HistoricalUserActivityDaily.user_id,
                func.sum(HistoricalUserActivityDaily.message_count).label("message_count"),
                func.max(HistoricalUserActivityDaily.last_message_at).label("last_message_at"),
            )
            .where(*historical_conditions)
            .group_by(HistoricalUserActivityDaily.user_id)
        )
    ).all()
    return _merge_leaderboard_rows(
        [(int(user_id), int(message_count or 0), last_message_at) for user_id, message_count, last_message_at in live_rows],
        [(int(user_id), int(message_count or 0), last_message_at) for user_id, message_count, last_message_at in historical_rows],
    )


async def _fetch_channel_counts_for_users(
    session: AsyncSession,
    server_id: int,
    user_ids: list[int],
    period_start: datetime | None,
    period_end_exclusive: datetime | None,
    include_channel_ids: set[int] | None = None,
    exclude_channel_ids: set[int] | None = None,
) -> dict[int, list[UserActivityChannelCountModel]]:
    if not user_ids:
        return {}
    live_conditions = _build_activity_filters(
        server_id=server_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_user_ids=set(user_ids),
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    live_rows = (
        await session.exec(
            select(
                MessageLog.user_id,
                MessageLog.channel_id,
                func.count().label("message_count"),
            )
            .where(*live_conditions)
            .group_by(MessageLog.user_id, MessageLog.channel_id)
        )
    ).all()
    historical_conditions = _build_historical_activity_filters(
        server_id=server_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_user_ids=set(user_ids),
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    historical_rows = (
        await session.exec(
            select(
                HistoricalUserActivityDaily.user_id,
                HistoricalUserActivityDaily.channel_id,
                func.sum(HistoricalUserActivityDaily.message_count).label("message_count"),
            )
            .where(*historical_conditions)
            .group_by(HistoricalUserActivityDaily.user_id, HistoricalUserActivityDaily.channel_id)
        )
    ).all()
    counts: dict[int, dict[int, int]] = {user_id: {} for user_id in user_ids}
    for user_id, channel_id, message_count in live_rows:
        user_key = int(user_id)
        channel_key = int(channel_id)
        counts.setdefault(user_key, {})[channel_key] = counts.setdefault(user_key, {}).get(channel_key, 0) + int(message_count or 0)
    for user_id, channel_id, message_count in historical_rows:
        user_key = int(user_id)
        channel_key = int(channel_id)
        counts.setdefault(user_key, {})[channel_key] = counts.setdefault(user_key, {}).get(channel_key, 0) + int(message_count or 0)
    return {
        user_id: [
            UserActivityChannelCountModel(channel_id=str(channel_id), message_count=message_count)
            for channel_id, message_count in sorted(user_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        for user_id, user_counts in counts.items()
    }


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
    include_channel_ids: list[str] | None = Query(
        default=None,
        description="Channel IDs to include (repeat parameter or use comma-separated IDs).",
    ),
    exclude_channel_ids: list[str] | None = Query(
        default=None,
        description="Channel IDs to exclude (repeat parameter or use comma-separated IDs).",
    ),
    refresh_channels: bool = Query(default=False, description="Bypass server channel cache for this request."),
    session: AsyncSession = Depends(get_session),
):
    period_start, period_end_exclusive, period_start_out, period_end_out = _resolve_period_bounds(
        date_from,
        date_to,
    )
    active_channel_ids = await _get_server_rendered_text_channel_ids(server_id, refresh=refresh_channels)
    include_channel_ids_set = _parse_id_set_filter(include_channel_ids, "include_channel_ids")
    exclude_channel_ids_set = _parse_id_set_filter(exclude_channel_ids, "exclude_channel_ids")
    effective_include_channel_ids = _intersect_optional_sets(active_channel_ids, include_channel_ids_set)

    # Date-filtered activity is computed from raw message logs.
    if period_start is not None or period_end_exclusive is not None:
        channel_rows = await _fetch_user_channel_counts(
            session=session,
            server_id=server_id,
            user_id=user_id,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
            include_channel_ids=effective_include_channel_ids,
            exclude_channel_ids=exclude_channel_ids_set,
        )
        latest_channel_id, latest_message_at = await _fetch_user_last_message_metadata(
            session=session,
            server_id=server_id,
            user_id=user_id,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
            include_channel_ids=effective_include_channel_ids,
            exclude_channel_ids=exclude_channel_ids_set,
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
        include_channel_ids=effective_include_channel_ids,
        exclude_channel_ids=exclude_channel_ids_set,
    )

    if not channel_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")

    latest_channel_id, latest_message_at = await _fetch_user_last_message_metadata(
        session=session,
        server_id=server_id,
        user_id=user_id,
        period_start=None,
        period_end_exclusive=None,
        include_channel_ids=effective_include_channel_ids,
        exclude_channel_ids=exclude_channel_ids_set,
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
    response: Response,
    limit: int = Query(default=50, ge=1, le=10000),
    all_users: bool = Query(default=False, description="Return every matching user instead of applying limit."),
    date_from: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD)."),
    date_to: date | None = Query(default=None, description="Inclusive UTC date (YYYY-MM-DD)."),
    channels_limit: int = Query(default=5, ge=1, le=20, description="Max channels per user in breakdown."),
    include_user_ids: list[str] | None = Query(
        default=None,
        description="User IDs to include (repeat parameter or use comma-separated IDs).",
    ),
    exclude_user_ids: list[str] | None = Query(
        default=None,
        description="User IDs to exclude (repeat parameter or use comma-separated IDs).",
    ),
    include_role_ids: list[str] | None = Query(
        default=None,
        description="Role IDs to include (repeat parameter or use comma-separated IDs).",
    ),
    exclude_role_ids: list[str] | None = Query(
        default=None,
        description="Role IDs to exclude (repeat parameter or use comma-separated IDs).",
    ),
    include_channel_ids: list[str] | None = Query(
        default=None,
        description="Channel IDs to include (repeat parameter or use comma-separated IDs).",
    ),
    exclude_channel_ids: list[str] | None = Query(
        default=None,
        description="Channel IDs to exclude (repeat parameter or use comma-separated IDs).",
    ),
    ignore_server_excludes: bool = Query(
        default=False,
        description="Do not apply server-level activity channel exclusions for this request.",
    ),
    refresh_member_roles: bool = Query(
        default=False,
        description="Bypass member-role cache for this request.",
    ),
    refresh_channels: bool = Query(default=False, description="Bypass server channel cache for this request."),
    session: AsyncSession = Depends(get_session),
):
    period_start, period_end_exclusive, period_start_out, period_end_out = _resolve_period_bounds(
        date_from,
        date_to,
    )
    include_user_ids_set = _parse_id_set_filter(include_user_ids, "include_user_ids")
    exclude_user_ids_set = _parse_id_set_filter(exclude_user_ids, "exclude_user_ids")
    include_role_ids_set = _parse_id_set_filter(include_role_ids, "include_role_ids")
    exclude_role_ids_set = _parse_id_set_filter(exclude_role_ids, "exclude_role_ids")
    include_channel_ids_set = _parse_id_set_filter(include_channel_ids, "include_channel_ids")
    exclude_channel_ids_set = _parse_id_set_filter(exclude_channel_ids, "exclude_channel_ids")
    server_excluded_channel_ids = await _fetch_server_activity_excluded_channel_ids(
        session=session,
        server_id=server_id,
    )
    effective_exclude_channel_ids, server_excludes_applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids=exclude_channel_ids_set,
        server_excluded_channel_ids=server_excluded_channel_ids,
        include_channel_ids=include_channel_ids_set,
        ignore_server_excludes=ignore_server_excludes,
    )
    _set_activity_leaderboard_meta_headers(
        response=response,
        server_excluded_channel_ids=server_excluded_channel_ids,
        server_excludes_applied=server_excludes_applied,
    )

    active_channel_ids = await _get_server_rendered_text_channel_ids(server_id, refresh=refresh_channels)
    effective_include_channel_ids = _intersect_optional_sets(active_channel_ids, include_channel_ids_set)
    if effective_include_channel_ids is not None and not effective_include_channel_ids:
        return []

    role_filters_requested = bool(include_role_ids_set or exclude_role_ids_set)
    sql_include_user_ids = include_user_ids_set if not include_role_ids_set else None
    leaderboard_rows = await _fetch_leaderboard_rows(
        session=session,
        server_id=server_id,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_user_ids=sql_include_user_ids,
        exclude_user_ids=exclude_user_ids_set,
        include_channel_ids=effective_include_channel_ids,
        exclude_channel_ids=effective_exclude_channel_ids,
    )
    requested_limit = None if all_users else limit
    if not role_filters_requested and requested_limit is not None:
        leaderboard_rows = leaderboard_rows[:requested_limit]

    if not leaderboard_rows:
        return []

    if role_filters_requested or (include_user_ids_set is not None and include_role_ids_set is not None):
        filtered_rows = []
        for user_id, message_count, last_message_at in leaderboard_rows:
            user_key = int(user_id)
            role_ids = await _get_member_role_ids_for_activity(
                server_id=server_id,
                user_id=user_key,
                refresh=refresh_member_roles,
            )
            if not _matches_role_filters(
                user_id=user_key,
                user_role_ids=role_ids,
                include_user_ids=include_user_ids_set,
                exclude_user_ids=exclude_user_ids_set,
                include_role_ids=include_role_ids_set,
                exclude_role_ids=exclude_role_ids_set,
            ):
                continue
            filtered_rows.append((user_key, int(message_count), last_message_at))
            if requested_limit is not None and len(filtered_rows) >= requested_limit:
                break
        leaderboard_rows = filtered_rows
    else:
        leaderboard_rows = [
            (int(user_id), int(message_count), last_message_at)
            for user_id, message_count, last_message_at in leaderboard_rows
        ]

    if not leaderboard_rows:
        return []

    user_ids = [user_id for user_id, _, _ in leaderboard_rows]
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

    channels_by_user = await _fetch_channel_counts_for_users(
        session=session,
        server_id=server_id,
        user_ids=user_ids,
        period_start=period_start,
        period_end_exclusive=period_end_exclusive,
        include_channel_ids=effective_include_channel_ids,
        exclude_channel_ids=effective_exclude_channel_ids,
    )
    channels_by_user = {
        user_id: channels[:channels_limit]
        for user_id, channels in channels_by_user.items()
    }

    warn_rows = (
        await session.exec(
            select(
                ModerationAction.target_user_id,
                ModerationAction.id,
                ModerationAction.created_at,
                ModerationAction.reason,
            )
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id.in_(user_ids),
                ModerationAction.action_type == ActionType.WARN,
                ModerationAction.is_active.is_(True),
            )
            .order_by(ModerationAction.target_user_id.asc(), ModerationAction.created_at.desc())
        )
    ).all()
    warnings_by_user: dict[int, list[UserActivityWarningModel]] = {}
    for target_user_id, action_id, created_at, reason in warn_rows:
        warnings_by_user.setdefault(int(target_user_id), []).append(
            UserActivityWarningModel(
                action_id=str(action_id),
                created_at=_as_naive_utc(created_at) or _naive_utcnow(),
                reason=reason,
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
                warn_count=len(warnings_by_user.get(user_key, [])),
                warnings=warnings_by_user.get(user_key, []),
                period_start=period_start_out,
                period_end=period_end_out,
            )
        )
    return result
