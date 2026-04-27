from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.moderation_actions import ModerationActionSummaryModel
from api.models.moderation_cases import ModerationCaseSummaryModel, ModerationRuleRef
from api.models.user_profiles import (
    MonitoredUserSummaryModel,
    TopRuleViolationModel,
    UserActivitySummaryModel,
    UserModerationActionSummaryModel,
    UserModerationCaseSummaryModel,
    UserProfileCardModel,
)
from api.services.moderation_actions_service import list_action_summaries
from api.services.moderation_cases_service import list_cases as list_cases_service
from api.services.moderation_core import get_nickname_history, to_nickname_record
from src.db.models import (
    CaseStatus,
    GlobalUser,
    MessageLog,
    ModerationAction,
    ModerationActionRuleCitation,
    ModerationCase,
    ModerationCaseUser,
    ModerationRule,
    MonitoredUser,
    MonitoredUserComment,
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

    monitored_row = (
        await session.exec(
            select(MonitoredUser).where(
                MonitoredUser.server_id == server_id,
                MonitoredUser.user_id == user_id,
            )
        )
    ).first()
    monitored_summary = None
    if monitored_row:
        monitored_comment_count = int(
            (
                await session.exec(
                    select(func.count())
                    .select_from(MonitoredUserComment)
                    .where(MonitoredUserComment.monitored_user_id == monitored_row.id)
                )
            ).one()
            or 0
        )
        monitored_summary = MonitoredUserSummaryModel(
            is_active=bool(monitored_row.is_active),
            reason=monitored_row.reason,
            since=monitored_row.created_at,
            comment_count=monitored_comment_count,
        )

    top_rule_rows = (
        await session.exec(
            select(
                ModerationActionRuleCitation.rule_id,
                ModerationActionRuleCitation.rule_code_snapshot,
                ModerationActionRuleCitation.rule_title_snapshot,
                func.count(ModerationActionRuleCitation.id).label("count"),
            )
            .join(
                ModerationAction,
                ModerationAction.id == ModerationActionRuleCitation.action_id,
            )
            .where(
                ModerationAction.server_id == server_id,
                ModerationAction.target_user_id == user_id,
            )
            .group_by(
                ModerationActionRuleCitation.rule_id,
                ModerationActionRuleCitation.rule_code_snapshot,
                ModerationActionRuleCitation.rule_title_snapshot,
            )
            .order_by(func.count(ModerationActionRuleCitation.id).desc())
            .limit(3)
        )
    ).all()
    top_rules_violated: list[TopRuleViolationModel] = []
    for row in top_rule_rows:
        citation_rule_id = row[0]
        citation_rule_code = row[1]
        citation_rule_title = row[2]
        citation_count = int(row[3] or 0)

        resolved_rule = await session.get(ModerationRule, citation_rule_id) if citation_rule_id is not None else None
        if resolved_rule:
            rule_ref = ModerationRuleRef(
                id=str(resolved_rule.id),
                code=resolved_rule.code,
                title=resolved_rule.title,
                deleted=False,
            )
        else:
            title = (citation_rule_title or "Rule").strip() or "Rule"
            if "(deleted)" not in title.lower():
                title = f"{title} (deleted)"
            rule_ref = ModerationRuleRef(
                id=None,
                code=citation_rule_code,
                title=title,
                deleted=True,
            )
        top_rules_violated.append(
            TopRuleViolationModel(
                rule=rule_ref,
                count=citation_count,
            )
        )

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
        monitored=monitored_summary,
        top_rules_violated=top_rules_violated,
    )


async def list_actions_for_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    limit: int = 200,
) -> list[ModerationActionSummaryModel]:
    return await list_action_summaries(
        session=session,
        server_id=server_id,
        target_user_id=user_id,
        limit=limit,
    )


async def list_cases_for_user(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    status_filter: CaseStatus | None = None,
    limit: int = 200,
) -> list[ModerationCaseSummaryModel]:
    return await list_cases_service(
        session=session,
        server_id=server_id,
        status_filter=status_filter,
        user_id=str(user_id),
        limit=limit,
    )
