from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.user_profiles import (
    UserActivityLeaderboardItemModel,
    UserActivitySummaryModel,
    UserActivityUpsertModel,
)
from src.db.database import get_session
from src.db.models import GlobalUser, Server, User, UserActivity

activity = APIRouter(prefix="/activity", tags=["activity"])


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    return UserActivitySummaryModel(
        user_id=str(item.user_id),
        server_id=str(item.server_id),
        channel_id=str(item.channel_id),
        message_count=item.message_count,
        last_message_at=item.last_message_at,
    )


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
    session: AsyncSession = Depends(get_session),
):
    activity_row = await session.get(UserActivity, (user_id, server_id))
    if not activity_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    return _to_activity_summary(activity_row)


@activity.get("/{server_id}/leaderboard", response_model=list[UserActivityLeaderboardItemModel])
async def get_server_activity_leaderboard(
    server_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.exec(
            select(UserActivity, GlobalUser, User)
            .join(GlobalUser, GlobalUser.discord_id == UserActivity.user_id)
            .join(
                User,
                (User.user_id == UserActivity.user_id) & (User.server_id == UserActivity.server_id),
            )
            .where(UserActivity.server_id == server_id)
            .order_by(UserActivity.message_count.desc(), UserActivity.last_message_at.desc())
            .limit(limit)
        )
    ).all()

    result: list[UserActivityLeaderboardItemModel] = []
    for activity_row, global_user, membership in rows:
        display_name = membership.server_nickname or global_user.username or str(activity_row.user_id)
        result.append(
            UserActivityLeaderboardItemModel(
                user_id=str(activity_row.user_id),
                username=global_user.username,
                server_nickname=membership.server_nickname,
                display_name=display_name,
                message_count=activity_row.message_count,
                last_message_at=activity_row.last_message_at,
            )
        )
    return result
