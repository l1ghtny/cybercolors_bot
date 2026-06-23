import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_cases import (
    ModerationCaseActionCreateFromCaseModel,
    ModerationCaseCreateModel,
)
from api.services.moderation_actions_service import create_action, get_action_details, get_server_history, list_action_summaries
from api.services.moderation_cases_service import (
    create_action_from_case,
    create_case,
    get_case_details,
    link_action_to_case,
    list_cases,
    remove_action_from_case,
)
from api.services.moderation_rules_service import create_manual_rule, delete_rule_permanently, get_rule_usage
from api.services.monitoring_service import (
    add_monitored_user_from_case,
    get_monitored_user_details,
    list_monitored_user_comments,
    list_monitored_users,
    upsert_monitored_user,
)
from api.services.moderation_users_service import build_user_profile_card, list_actions_for_user, list_cases_for_user
from src.db.database import get_async_session
from src.db.models import (
    ActionType,
    CaseStatus,
    GlobalUser,
    ModerationActionRuleCitation,
    ModerationCase,
    ModerationCaseRuleCitation,
    Server,
    User,
)


def _make_discord_id() -> int:
    # Keep IDs inside bigint while staying very unlikely to collide with existing fixtures.
    return 7_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _seed_server_and_members(
    session,
    server_id: int,
    users: list[tuple[int, str]],
) -> None:
    session.add(
        Server(
            server_id=server_id,
            server_name=f"server-{server_id}",
            bot_active=True,
        )
    )
    for user_id, username in users:
        session.add(GlobalUser(discord_id=user_id, username=username))
        session.add(
            User(
                user_id=user_id,
                server_id=server_id,
                server_nickname=f"{username}-nick",
                is_member=True,
            )
        )
    await session.flush()



def _make_action_payload(
    *,
    server_id: int,
    moderator_id: int,
    target_id: int,
    target_name: str,
    reason: str,
    case_id: str | None = None,
) -> ModerationActionCreate:
    return ModerationActionCreate(
        action_type=ActionType.WARN,
        moderator_user_id=moderator_id,
        reason=reason,
        rule_ids=[],
        commentary=None,
        expires_at=None,
        case_id=case_id,
        target_user_id=target_id,
        target_user_name=target_name,
        target_user_joined_at=datetime.now(timezone.utc).replace(tzinfo=None),
        target_user_server_nickname=f"{target_name}-nick",
        server_id=server_id,
        server_name=f"server-{server_id}",
    )


async def _scenario_rule_citations_survive_hard_delete() -> None:
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()

    async with get_async_session() as session:
        await _seed_server_and_members(
            session=session,
            server_id=server_id,
            users=[
                (moderator_id, "mod"),
                (target_id, "target"),
            ],
        )
        rule = await create_manual_rule(
            session=session,
            server_id=server_id,
            title="No insults",
            description="Insults are not allowed",
            code="1",
            sort_order=1,
            created_by_user_id=moderator_id,
        )
        moderation_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Case A",
                summary="Case summary",
                rule_ids=[str(rule.id)],
                users=[],
            ),
            opened_by_user_id=moderator_id,
        )

        action = await create_action_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
            body=ModerationCaseActionCreateFromCaseModel(
                action_type=ActionType.WARN,
                reason="warning reason",
                target_user_id=str(target_id),
                rule_ids=None,
                expires_at=None,
            ),
            actor_user_id=moderator_id,
        )
        assert action.case_id == moderation_case.id
        assert len(action.rules) == 1
        assert action.rules[0].id == str(rule.id)

        usage = await get_rule_usage(session=session, server_id=server_id, rule_id=rule.id)
        assert usage.rule_id == str(rule.id)
        assert usage.usage_count >= 2
        assert usage.action_count >= 1
        assert usage.case_count >= 1
        assert usage.recent_citations
        assert {item.source for item in usage.recent_citations} >= {"action", "case"}
        assert usage.top_offenders
        assert usage.top_offenders[0].count >= 1

        await delete_rule_permanently(session=session, server_id=server_id, rule_id=rule.id)

        action_citations = (
            await session.exec(
                select(ModerationActionRuleCitation).where(
                    ModerationActionRuleCitation.server_id == server_id,
                )
            )
        ).all()
        assert action_citations
        assert all(item.rule_id is None for item in action_citations)
        assert all(item.rule_deleted_at is not None for item in action_citations)

        case_citations = (
            await session.exec(
                select(ModerationCaseRuleCitation).where(
                    ModerationCaseRuleCitation.server_id == server_id,
                )
            )
        ).all()
        assert case_citations
        assert all(item.rule_id is None for item in case_citations)
        assert all(item.rule_deleted_at is not None for item in case_citations)

        details = await get_case_details(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
        )
        assert len(details.case.rules) == 1
        assert details.case.rules[0].id is None
        assert details.case.rules[0].deleted is True

        history = await get_server_history(
            session=session,
            server_id=server_id,
            target_user_id=str(target_id),
            limit=20,
        )
        assert history
        assert history[0].rules[0].id is None
        assert history[0].rules[0].deleted is True

        with pytest.raises(HTTPException) as exc:
            await get_rule_usage(session=session, server_id=server_id, rule_id=rule.id)
        assert exc.value.status_code == 404
        await session.rollback()


async def _scenario_monitoring_cross_refs_and_profile_rule_stats() -> None:
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    related_id = _make_discord_id()
    outsider_id = _make_discord_id()

    async with get_async_session() as session:
        await _seed_server_and_members(
            session=session,
            server_id=server_id,
            users=[
                (moderator_id, "mod"),
                (target_id, "target"),
                (related_id, "related"),
                (outsider_id, "outsider"),
            ],
        )
        rule = await create_manual_rule(
            session=session,
            server_id=server_id,
            title="No spam",
            description="Spam is not allowed",
            code="2",
            sort_order=2,
            created_by_user_id=moderator_id,
        )
        await upsert_monitored_user(
            session=session,
            server_id=server_id,
            user_id=target_id,
            reason="Already suspicious",
            added_by_user_id=moderator_id,
        )

        moderation_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Case B",
                summary="Case with watchlist subject",
                rule_ids=[str(rule.id)],
                users=[str(related_id)],
            ),
            opened_by_user_id=moderator_id,
        )

        details = await get_case_details(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
        )
        assert any(note.author.user_id == "system" for note in details.notes)

        created_action = await create_action_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
            body=ModerationCaseActionCreateFromCaseModel(
                action_type=ActionType.WARN,
                reason="spam warning",
                target_user_id=str(target_id),
                rule_ids=None,
                expires_at=None,
            ),
            actor_user_id=moderator_id,
        )

        action_summaries = await list_action_summaries(
            session=session,
            server_id=server_id,
            target_user_id=target_id,
            limit=20,
        )
        assert action_summaries
        action_summary = action_summaries[0]
        assert action_summary.id == created_action.id
        assert action_summary.rules_count >= 1
        assert action_summary.case_id == moderation_case.id

        per_user_actions = await list_actions_for_user(
            session=session,
            server_id=server_id,
            user_id=target_id,
            limit=20,
        )
        assert per_user_actions
        assert per_user_actions[0].id == created_action.id

        action_details = await get_action_details(
            session=session,
            server_id=server_id,
            action_id=UUID(created_action.id),
        )
        assert action_details.id == created_action.id
        assert action_details.rules

        case_summaries = await list_cases(
            session=session,
            server_id=server_id,
        )
        assert case_summaries
        summary = case_summaries[0]
        assert summary.id == moderation_case.id
        assert summary.stats.linked_actions_count >= 1
        assert summary.stats.linked_users_count >= 2
        assert any(item.user.user_id == str(target_id) for item in summary.linked_users)

        related_summaries = await list_cases_for_user(
            session=session,
            server_id=server_id,
            user_id=target_id,
            limit=20,
        )
        assert any(item.id == moderation_case.id for item in related_summaries)

        monitored_details = await get_monitored_user_details(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )
        assert monitored_details.comment_count == 0
        assert monitored_details.counts.cases_total >= 1
        assert monitored_details.counts.cases_open >= 1
        assert monitored_details.counts.actions_total >= 1
        assert any(item.id == moderation_case.id for item in monitored_details.related_cases)
        assert monitored_details.recent_actions

        monitored_list = await list_monitored_users(
            session=session,
            server_id=server_id,
            active_only=True,
            include_counts=True,
        )
        monitored_target = next(item for item in monitored_list if item.user.user_id == str(target_id))
        assert monitored_target.counts is not None
        assert monitored_target.counts.actions_total >= 1

        monitored_from_case = await add_monitored_user_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
            user_id=related_id,
            reason=None,
            added_by_user_id=moderator_id,
        )
        assert monitored_from_case.reason == f"From case: {moderation_case.title}"
        monitored_from_case_again = await add_monitored_user_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
            user_id=related_id,
            reason="ignored because active",
            added_by_user_id=moderator_id,
        )
        assert monitored_from_case_again.id == monitored_from_case.id
        assert monitored_from_case_again.reason == monitored_from_case.reason

        comments = await list_monitored_user_comments(
            session=session,
            server_id=server_id,
            user_id=related_id,
            limit=20,
        )
        assert any("Added from case" in item.comment for item in comments)

        with pytest.raises(HTTPException) as exc:
            await add_monitored_user_from_case(
                session=session,
                server_id=server_id,
                case_id=UUID(moderation_case.id),
                user_id=outsider_id,
                reason=None,
                added_by_user_id=moderator_id,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail == "user_not_in_case"

        profile = await build_user_profile_card(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )
        assert profile.monitored is True
        assert profile.monitored_summary is not None
        assert profile.top_rules_violated
        assert profile.top_rules_violated[0].usage_count >= 1
        assert profile.top_rules_violated[0].last_cited_at is not None
        await session.rollback()



async def _scenario_case_action_rich_links_and_case_badges() -> None:
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    related_id = _make_discord_id()

    async with get_async_session() as session:
        await _seed_server_and_members(
            session=session,
            server_id=server_id,
            users=[
                (moderator_id, "mod"),
                (target_id, "target"),
                (related_id, "related"),
            ],
        )
        rule = await create_manual_rule(
            session=session,
            server_id=server_id,
            title="No raids",
            description="Raid behavior is not allowed",
            code="3",
            sort_order=3,
            created_by_user_id=moderator_id,
        )

        source_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Case C",
                summary="Source case",
                rule_ids=[str(rule.id)],
                users=[str(related_id)],
            ),
            opened_by_user_id=moderator_id,
        )
        target_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Case D",
                summary="Target case",
                rule_ids=[],
                users=[str(related_id)],
            ),
            opened_by_user_id=moderator_id,
        )
        generic_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Case E",
                summary="Generic create case",
                rule_ids=[],
                users=[],
            ),
            opened_by_user_id=moderator_id,
        )
        archived_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Case F",
                summary="Archived case",
                rule_ids=[],
                users=[],
            ),
            opened_by_user_id=moderator_id,
        )

        archived_case_row = await session.get(ModerationCase, UUID(archived_case.id))
        assert archived_case_row is not None
        archived_case_row.status = CaseStatus.ARCHIVED
        archived_case_row.closed_by_user_id = moderator_id
        archived_case_row.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(archived_case_row)
        await session.flush()

        case_created_action = await create_action_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(source_case.id),
            body=ModerationCaseActionCreateFromCaseModel(
                action_type=ActionType.WARN,
                reason="raid warning",
                target_user_id=None,
                rule_ids=None,
                expires_at=None,
            ),
            actor_user_id=moderator_id,
        )
        assert case_created_action.case_id == source_case.id
        assert case_created_action.case_title == source_case.title
        assert case_created_action.rules
        assert case_created_action.rules[0].id == str(rule.id)

        source_details = await get_case_details(
            session=session,
            server_id=server_id,
            case_id=UUID(source_case.id),
        )
        assert source_details.case.linked_action_ids == [case_created_action.id]
        assert source_details.case.linked_actions
        linked_action = source_details.case.linked_actions[0]
        assert linked_action.id == case_created_action.id
        assert linked_action.target_user.user_id == str(target_id)
        assert linked_action.moderator.user_id == str(moderator_id)
        assert linked_action.rules
        assert linked_action.rules[0].id == str(rule.id)

        action_summaries = await list_action_summaries(
            session=session,
            server_id=server_id,
            target_user_id=target_id,
            limit=20,
        )
        assert action_summaries
        first_summary = next(item for item in action_summaries if item.id == case_created_action.id)
        assert first_summary.case_id == source_case.id
        assert first_summary.case_title == source_case.title

        generic_action = await create_action(
            session=session,
            action=_make_action_payload(
                server_id=server_id,
                moderator_id=moderator_id,
                target_id=target_id,
                target_name="target",
                reason="generic linked warning",
                case_id=generic_case.id,
            ),
            moderator_user_id=moderator_id,
        )
        generic_action_details = await get_action_details(
            session=session,
            server_id=server_id,
            action_id=generic_action.id,
        )
        assert generic_action_details.case_id == generic_case.id
        assert generic_action_details.case_title == generic_case.title

        standalone_action = await create_action(
            session=session,
            action=_make_action_payload(
                server_id=server_id,
                moderator_id=moderator_id,
                target_id=target_id,
                target_name="target",
                reason="standalone warning",
            ),
            moderator_user_id=moderator_id,
        )

        with pytest.raises(HTTPException) as exc:
            await create_action(
                session=session,
                action=_make_action_payload(
                    server_id=server_id,
                    moderator_id=moderator_id,
                    target_id=target_id,
                    target_name="target",
                    reason="blocked archived warning",
                    case_id=archived_case.id,
                ),
                moderator_user_id=moderator_id,
            )
        assert exc.value.status_code == 409

        with pytest.raises(HTTPException) as exc:
            await link_action_to_case(
                session=session,
                server_id=server_id,
                case_id=UUID(archived_case.id),
                moderation_action_id=str(standalone_action.id),
                linked_by_user_id=moderator_id,
            )
        assert exc.value.status_code == 409

        moved_case = await link_action_to_case(
            session=session,
            server_id=server_id,
            case_id=UUID(target_case.id),
            moderation_action_id=case_created_action.id,
            linked_by_user_id=moderator_id,
        )
        assert case_created_action.id in moved_case.linked_action_ids

        moved_action_details = await get_action_details(
            session=session,
            server_id=server_id,
            action_id=UUID(case_created_action.id),
        )
        assert moved_action_details.case_id == target_case.id
        assert moved_action_details.case_title == target_case.title

        source_details_after_move = await get_case_details(
            session=session,
            server_id=server_id,
            case_id=UUID(source_case.id),
        )
        assert case_created_action.id not in source_details_after_move.case.linked_action_ids

        moved_summaries = await list_action_summaries(
            session=session,
            server_id=server_id,
            target_user_id=target_id,
            limit=20,
        )
        moved_summary = next(item for item in moved_summaries if item.id == case_created_action.id)
        assert moved_summary.case_id == target_case.id
        assert moved_summary.case_title == target_case.title

        unlinked_case = await remove_action_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(target_case.id),
            action_id=UUID(case_created_action.id),
        )
        assert case_created_action.id not in unlinked_case.linked_action_ids

        unlinked_action_details = await get_action_details(
            session=session,
            server_id=server_id,
            action_id=UUID(case_created_action.id),
        )
        assert unlinked_action_details.case_id is None
        assert unlinked_action_details.case_title is None
        await session.rollback()


def test_moderation_refactor_integration():
    async def scenario() -> None:
        await _scenario_rule_citations_survive_hard_delete()
        await _scenario_monitoring_cross_refs_and_profile_rule_stats()
        await _scenario_case_action_rich_links_and_case_badges()

    asyncio.run(scenario())
