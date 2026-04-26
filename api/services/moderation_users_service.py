from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionRead
from api.models.moderation_cases import ModerationCaseReadModel
from api.models.user_profiles import (
    UserActivitySummaryModel,
    UserModerationActionSummaryModel,
    UserModerationCaseSummaryModel,
    UserProfileCardModel,
)
from api.services.moderation_core import get_nickname_history, to_case_read, to_moderation_history, to_nickname_record
from api.services.moderation_queries import query_moderation_actions
from src.db.models import (
    CaseStatus,
    GlobalUser,
    MessageLog,
    ModerationAction,
    ModerationCase,
    ModerationCaseUser,
    Server,
    User,
)


def _cases_for_user_clause(user_id: int):
    return or_(
        ModerationCase.target_user_id == user_id,
        ModerationCase.id.in_(select(ModerationCaseUser.case_id).where(ModerationCaseUser.user_id == user_id)),
    )


async def build_user_profile_card(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    history_limit: int = 20,
    actions_limit: int = 10,
    cases_limit: int = 10,
) -> UserProfileCardModel:
    server = await session.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")

    global_user = await session.get(GlobalUser, user_id)
    if not global_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    membership = (await session.exec(select(User).where(User.server_id == server_id, User.user_id == user_id))).first()
    display_name = membership.server_nickname if membership and membership.server_nickname else (global_user.username or str(user_id))

    activity_totals = (
        await session.exec(
            select(
                func.count().label("message_count"),
                func.max(MessageLog.created_at).label("last_message_at"),
            ).where(
                MessageLog.server_id == server_id,
                MessageLog.user_id == user_id,
            )
        )
    ).one()
    activity_message_count = int(activity_totals[0] or 0)
    activity_last_message_at = activity_totals[1]
    latest_channel_id = (
        await session.exec(
            select(MessageLog.channel_id)
            .where(
                MessageLog.server_id == server_id,
                MessageLog.user_id == user_id,
            )
            .order_by(MessageLog.created_at.desc(), MessageLog.message_id.desc())
            .limit(1)
        )
    ).first()
    activity_payload = (
        UserActivitySummaryModel(
            user_id=str(user_id),
            server_id=str(server_id),
            channel_id=str(latest_channel_id) if latest_channel_id is not None else None,
            message_count=activity_message_count,
            last_message_at=activity_last_message_at,
        )
        if activity_message_count > 0
        else None
    )

    nickname_history = await get_nickname_history(session, server_id, user_id, history_limit)
    cases_for_user = _cases_for_user_clause(user_id)

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

    cases = (
        await session.exec(
            select(ModerationCase)
            .where(
                ModerationCase.server_id == server_id,
                cases_for_user,
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
                cases_for_user,
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


async def list_actions_for_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
) -> list[ModerationActionRead]:
    actions = await query_moderation_actions(
        session=session,
        server_id=server_id,
        target_user_id=user_id,
        limit=limit,
    )
    return to_moderation_history(actions)


async def list_cases_for_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    status_filter: CaseStatus | None = None,
    limit: int = 200,
) -> list[ModerationCaseReadModel]:
    statement = select(ModerationCase).where(
        ModerationCase.server_id == server_id,
        _cases_for_user_clause(user_id),
    )
    if status_filter:
        statement = statement.where(ModerationCase.status == status_filter)

    statement = statement.order_by(ModerationCase.created_at.desc()).limit(limit)
    cases = (await session.exec(statement)).all()
    return [await to_case_read(case, session) for case in cases]
