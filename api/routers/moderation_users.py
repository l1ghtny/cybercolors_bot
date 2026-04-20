from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionRead
from api.models.moderation_cases import ModerationCaseReadModel
from api.models.user_profiles import (
    NicknameLogModel,
    NicknameRecordModel,
    UserActivitySummaryModel,
    UserModerationActionSummaryModel,
    UserModerationCaseSummaryModel,
    UserProfileCardModel,
)
from api.services.moderation_core import (
    get_nickname_history,
    get_or_create_server_record,
    get_or_create_user_membership,
    naive_utcnow,
    to_case_read,
    to_moderation_history,
    to_nickname_record,
)
from api.services.moderation_queries import query_moderation_actions
from src.db.database import get_session
from src.db.models import (
    CaseStatus,
    GlobalUser,
    ModerationAction,
    ModerationCase,
    ModerationCaseUser,
    PastNickname,
    Server,
    User,
    UserActivity,
)

moderation_users_router = APIRouter()


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
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    membership = (
        await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))
    ).first()
    display_name = (
        membership.server_nickname
        if membership and membership.server_nickname
        else (global_user.username or str(user_id))
    )

    activity = await session.get(UserActivity, (user_id, server_id))
    activity_payload = (
        UserActivitySummaryModel(
            user_id=str(activity.user_id),
            server_id=str(activity.server_id),
            channel_id=str(activity.channel_id),
            message_count=activity.message_count,
            last_message_at=activity.last_message_at,
        )
        if activity
        else None
    )

    nickname_history = await get_nickname_history(session, server_id, user_id, history_limit)

    actions = (
        await session.exec(
            select(ModerationAction)
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == user_id,
            )
            .options(selectinload(ModerationAction.global_user_moderator))
            .order_by(ModerationAction.created_at.desc())
            .limit(actions_limit)
        )
    ).all()
    actions_count = (
        await session.exec(
            select(func.count())
            .select_from(ModerationAction)
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == user_id,
            )
        )
    ).one()

    cases_for_user_clause = or_(
        ModerationCase.target_user_id == user_id,
        ModerationCase.id.in_(
            select(ModerationCaseUser.case_id).where(ModerationCaseUser.user_id == user_id)
        ),
    )

    cases = (
        await session.exec(
            select(ModerationCase)
            .where(
                ModerationCase.server_id == server_id,
                cases_for_user_clause,
            )
            .order_by(ModerationCase.created_at.desc())
            .limit(cases_limit)
        )
    ).all()
    open_cases_count = (
        await session.exec(
            select(func.count())
            .select_from(ModerationCase)
            .where(
                ModerationCase.server_id == server_id,
                cases_for_user_clause,
                ModerationCase.status == CaseStatus.OPEN,
            )
        )
    ).one()

    return UserProfileCardModel(
        user_id=str(user_id),
        username=global_user.username,
        server_nickname=membership.server_nickname if membership else None,
        display_name=display_name,
        avatar_hash=global_user.avatar_hash,
        joined_discord=global_user.joined_discord,
        is_member=membership.is_member if membership else False,
        flagged_absent_at=membership.flagged_absent_at if membership else None,
        activity=activity_payload,
        nickname_history=[to_nickname_record(item) for item in nickname_history],
        moderation_actions_count=int(actions_count),
        open_cases_count=int(open_cases_count),
        recent_actions=[
            UserModerationActionSummaryModel(
                id=str(action.id),
                action_type=action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type),
                reason=action.reason,
                created_at=action.created_at,
                moderator_user_id=str(action.moderator_user_id),
                moderator_username=(action.global_user_moderator.username if action.global_user_moderator else None),
            )
            for action in actions
        ],
        recent_cases=[
            UserModerationCaseSummaryModel(
                id=str(case.id),
                title=case.title,
                status=case.status,
                created_at=case.created_at,
            )
            for case in cases
        ],
    )


@moderation_users_router.get("/users/{server_id}/{user_id}/actions", response_model=List[ModerationActionRead])
async def get_actions_for_user(
    server_id: int,
    user_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=user_id,
        limit=limit,
    )
    return to_moderation_history(actions)


@moderation_users_router.get("/users/{server_id}/{user_id}/cases", response_model=List[ModerationCaseReadModel])
async def get_cases_for_user(
    server_id: int,
    user_id: int,
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    statement = select(ModerationCase).where(
        ModerationCase.server_id == server_id,
        or_(
            ModerationCase.target_user_id == user_id,
            ModerationCase.id.in_(
                select(ModerationCaseUser.case_id).where(ModerationCaseUser.user_id == user_id)
            ),
        ),
    )
    if status_filter:
        statement = statement.where(ModerationCase.status == status_filter)

    statement = statement.order_by(ModerationCase.created_at.desc()).limit(limit)
    cases = (await session.exec(statement)).all()
    return [await to_case_read(case, session) for case in cases]
