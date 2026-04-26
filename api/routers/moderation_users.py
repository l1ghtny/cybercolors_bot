from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.current_user import get_optional_current_discord_user_id, resolve_actor_user_id
from api.dependencies.server_access import require_server_dashboard_access
from api.models.monitoring import (
    MonitoredUserCommentCreateModel,
    MonitoredUserCommentReadModel,
    MonitoredUserCreateModel,
    MonitoredUserReadModel,
    MonitoredUserStatusEventReadModel,
    MonitoredUserUpdateModel,
)
from api.models.moderation_actions import ModerationActionRead
from api.models.moderation_cases import ModerationCaseReadModel
from api.models.user_profiles import (
    NicknameLogModel,
    NicknameRecordModel,
    UserProfileCardModel,
)
from api.services.monitoring_service import (
    add_monitored_user_comment,
    list_monitored_users as list_monitored_users_service,
    list_monitored_user_comments,
    list_monitored_user_status_events,
    update_monitored_user,
    upsert_monitored_user,
)
from api.services.moderation_core import (
    get_nickname_history,
    get_or_create_server_record,
    get_or_create_user_membership,
    naive_utcnow,
    to_nickname_record,
)
from api.services.moderation_users_service import (
    build_user_profile_card,
    list_actions_for_user as list_actions_for_user_service,
    list_cases_for_user as list_cases_for_user_service,
)
from src.db.database import get_session
from src.db.models import (
    CaseStatus,
    PastNickname,
)

moderation_users_router = APIRouter(
    dependencies=[Depends(require_server_dashboard_access)],
)


@moderation_users_router.post(
    "/users/{server_id}/{user_id}/nicknames",
    response_model=NicknameRecordModel,
    status_code=status.HTTP_201_CREATED,
)
async def log_user_nickname(
    server_id: int,
    user_id: int,
    body: NicknameLogModel,
    session: AsyncSession = Depends(get_session),
):
    server = await get_or_create_server_record(server_id, session)
    _, membership = await get_or_create_user_membership(
        session=session,
        server_id=server_id,
        user_id=user_id,
        server_nickname=body.nickname,
    )

    latest = (
        await session.exec(
            select(PastNickname)
            .where(PastNickname.user_id == user_id, PastNickname.server_id == server_id)
            .order_by(PastNickname.recorded_at.desc())
            .limit(1)
        )
    ).first()
    if latest and latest.discord_name == body.nickname:
        return to_nickname_record(latest)

    nickname_record = PastNickname(
        user_id=user_id,
        discord_name=body.nickname,
        server_name=body.server_name or server.server_name or str(server_id),
        server_id=server_id,
        recorded_at=body.recorded_at or naive_utcnow(),
    )
    session.add(nickname_record)

    if membership.server_nickname != body.nickname:
        membership.server_nickname = body.nickname
        session.add(membership)

    await session.flush()
    await session.refresh(nickname_record)
    return to_nickname_record(nickname_record)


@moderation_users_router.get("/users/{server_id}/{user_id}/nicknames", response_model=list[NicknameRecordModel])
async def get_user_nickname_history(
    server_id: int,
    user_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    history = await get_nickname_history(session, server_id, user_id, limit)
    return [to_nickname_record(item) for item in history]


@moderation_users_router.get("/users/{server_id}/{user_id}/profile", response_model=UserProfileCardModel)
async def get_user_profile_card(
    server_id: int,
    user_id: int,
    history_limit: int = Query(default=20, ge=1, le=100),
    actions_limit: int = Query(default=10, ge=1, le=50),
    cases_limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    return await build_user_profile_card(
        session=session,
        server_id=server_id,
        user_id=user_id,
        history_limit=history_limit,
        actions_limit=actions_limit,
        cases_limit=cases_limit,
    )


@moderation_users_router.get("/users/{server_id}/{user_id}/actions", response_model=List[ModerationActionRead])
async def get_actions_for_user(
    server_id: int,
    user_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    return await list_actions_for_user_service(session=session, server_id=server_id, user_id=user_id, limit=limit)


@moderation_users_router.get("/users/{server_id}/{user_id}/cases", response_model=List[ModerationCaseReadModel])
async def get_cases_for_user(
    server_id: int,
    user_id: int,
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    return await list_cases_for_user_service(
        session=session,
        server_id=server_id,
        user_id=user_id,
        status_filter=status_filter,
        limit=limit,
    )


@moderation_users_router.get("/users/{server_id}/monitored", response_model=list[MonitoredUserReadModel])
async def get_monitored_users(
    server_id: int,
    active_only: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
):
    return await list_monitored_users_service(session=session, server_id=server_id, active_only=active_only)


@moderation_users_router.post(
    "/users/{server_id}/monitored",
    response_model=MonitoredUserReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def add_monitored_user(
    server_id: int,
    body: MonitoredUserCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    added_by_user_id = resolve_actor_user_id(body.added_by_user_id, current_user_id)
    return await upsert_monitored_user(
        session=session,
        server_id=server_id,
        user_id=int(body.user_id),
        reason=body.reason,
        added_by_user_id=added_by_user_id,
    )


@moderation_users_router.patch("/users/{server_id}/monitored/{user_id}", response_model=MonitoredUserReadModel)
async def patch_monitored_user(
    server_id: int,
    user_id: int,
    body: MonitoredUserUpdateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    updated_by_user_id = resolve_actor_user_id(body.updated_by_user_id, current_user_id)
    try:
        return await update_monitored_user(
            session=session,
            server_id=server_id,
            user_id=user_id,
            reason=body.reason,
            is_active=body.is_active,
            updated_by_user_id=updated_by_user_id,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored user not found")


@moderation_users_router.get(
    "/users/{server_id}/monitored/{user_id}/comments",
    response_model=list[MonitoredUserCommentReadModel],
)
async def get_monitored_user_comments(
    server_id: int,
    user_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await list_monitored_user_comments(
            session=session,
            server_id=server_id,
            user_id=user_id,
            limit=limit,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored user not found")


@moderation_users_router.post(
    "/users/{server_id}/monitored/{user_id}/comments",
    response_model=MonitoredUserCommentReadModel,
    status_code=status.HTTP_201_CREATED,
)
async def post_monitored_user_comment(
    server_id: int,
    user_id: int,
    body: MonitoredUserCommentCreateModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int | None = Depends(get_optional_current_discord_user_id),
):
    author_user_id = resolve_actor_user_id(body.author_user_id, current_user_id)
    try:
        return await add_monitored_user_comment(
            session=session,
            server_id=server_id,
            user_id=user_id,
            comment=body.comment,
            author_user_id=author_user_id,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored user not found")


@moderation_users_router.get(
    "/users/{server_id}/monitored/{user_id}/status-history",
    response_model=list[MonitoredUserStatusEventReadModel],
)
async def get_monitored_user_status_history(
    server_id: int,
    user_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await list_monitored_user_status_events(
            session=session,
            server_id=server_id,
            user_id=user_id,
            limit=limit,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitored user not found")
