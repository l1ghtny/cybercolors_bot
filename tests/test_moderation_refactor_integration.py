import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import select

from api.models.moderation_cases import (
    ModerationCaseActionCreateFromCaseModel,
    ModerationCaseCreateModel,
)
from api.services.moderation_actions_service import get_server_history
from api.services.moderation_cases_service import create_action_from_case, create_case, get_case_details
from api.services.moderation_rules_service import create_manual_rule, delete_rule_permanently, get_rule_usage
from api.services.monitoring_service import (
    add_monitored_user_from_case,
    get_monitored_user_details,
    upsert_monitored_user,
)
from api.services.moderation_users_service import build_user_profile_card
from src.db.database import get_async_session
from src.db.models import (
    ActionType,
    GlobalUser,
    ModerationActionRuleCitation,
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
        assert usage.action_count >= 1
        assert usage.case_count >= 1

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

        await create_action_from_case(
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

        monitored_details = await get_monitored_user_details(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )
        assert monitored_details.comment_count == 0
        assert any(item.id == moderation_case.id for item in monitored_details.related_cases)
        assert monitored_details.recent_actions

        monitored_from_case = await add_monitored_user_from_case(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
            user_id=related_id,
            reason=None,
            added_by_user_id=moderator_id,
        )
        assert monitored_from_case.reason == moderation_case.title

        with pytest.raises(HTTPException) as exc:
            await add_monitored_user_from_case(
                session=session,
                server_id=server_id,
                case_id=UUID(moderation_case.id),
                user_id=outsider_id,
                reason=None,
                added_by_user_id=moderator_id,
            )
        assert exc.value.status_code == 422

        profile = await build_user_profile_card(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )
        assert profile.monitored is not None
        assert profile.top_rules_violated
        assert profile.top_rules_violated[0].count >= 1
        await session.rollback()


def test_moderation_refactor_integration():
    async def scenario() -> None:
        await _scenario_rule_citations_survive_hard_delete()
        await _scenario_monitoring_cross_refs_and_profile_rule_stats()

    asyncio.run(scenario())
