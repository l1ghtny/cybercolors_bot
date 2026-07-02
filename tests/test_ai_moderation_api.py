import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import SQLModel, select
from starlette.routing import Match

from api.api_main import app
from api.models.ai_moderation import AIApproveSuggestionModel, AIDismissSuggestionModel
from api.services.ai_moderation import approve_ai_suggestion, dismiss_ai_suggestion, get_ai_suggestion_stream_state, list_ai_decisions, list_ai_suggestions
from api.services.server_overview import build_server_overview
from src.db.database import engine, get_async_session
from src.db.models import AIModerationDecision, GlobalUser, MonitoredUser, Server, User
from tests.db_helpers import ensure_pgvector_or_skip


def _make_discord_id() -> int:
    return 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _assert_route(path: str, method: str, expected_path: str):
    scope = {"type": "http", "method": method, "path": path}
    for route in app.routes:
        match, _child_scope = route.matches(scope)
        if match == Match.FULL:
            assert route.path == expected_path
            return
    raise AssertionError(f"Route did not match: {method} {path}")


def test_ai_moderation_routes_are_registered():
    _assert_route("/servers/123/ai/suggestions", "GET", "/servers/{server_id}/ai/suggestions")
    _assert_route("/servers/123/ai/suggestions/stream", "GET", "/servers/{server_id}/ai/suggestions/stream")
    _assert_route(
        "/servers/123/ai/suggestions/11111111-1111-1111-1111-111111111111/approve",
        "POST",
        "/servers/{server_id}/ai/suggestions/{suggestion_id}/approve",
    )
    _assert_route(
        "/servers/123/ai/suggestions/11111111-1111-1111-1111-111111111111/tweak",
        "POST",
        "/servers/{server_id}/ai/suggestions/{suggestion_id}/tweak",
    )
    _assert_route(
        "/servers/123/ai/suggestions/11111111-1111-1111-1111-111111111111/dismiss",
        "POST",
        "/servers/{server_id}/ai/suggestions/{suggestion_id}/dismiss",
    )
    _assert_route("/servers/123/ai/decisions", "GET", "/servers/{server_id}/ai/decisions")


async def _ai_moderation_api_scenario() -> None:
    await engine.dispose()
    async with engine.begin() as conn:
        await ensure_pgvector_or_skip(conn)
        await conn.run_sync(SQLModel.metadata.create_all)
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    channel_id = _make_discord_id()
    archive_channel_id = _make_discord_id()
    archive_message_id = _make_discord_id()
    now = _naive_now()
    decision_id = uuid4()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="ai-api-test", bot_active=True))
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target", avatar_hash="avatar"))
        session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
        session.add(User(user_id=target_id, server_id=server_id, server_nickname="target-nick", is_member=True))
        await session.flush()
        session.add(
            AIModerationDecision(
                id=decision_id,
                server_id=server_id,
                channel_id=channel_id,
                message_id=_make_discord_id(),
                author_user_id=target_id,
                message_content="flagged message",
                attachments_json=[{"filename": "proof.png"}],
                archive_channel_id=archive_channel_id,
                archive_message_id=archive_message_id,
                provider="fake",
                model="test-model",
                strictness="high",
                flagged=True,
                severity="high",
                categories=["spam"],
                reason="Likely spam",
                suggested_action="warn",
                rule_ids=[],
                status="pending_review",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with get_async_session() as session:
        suggestions = await list_ai_suggestions(session=session, server_id=server_id)
        assert suggestions.unread_count == 1
        assert len(suggestions.items) == 1
        item = suggestions.items[0]
        assert item.id == str(decision_id)
        assert item.message.content == "flagged message"
        assert item.message.attachments == [{"filename": "proof.png"}]
        assert item.message.channel_deleted is True
        assert item.message.archive_channel_id == str(archive_channel_id)
        assert item.message.archive_message_id == str(archive_message_id)
        assert item.message.archive_jump_url == f"https://discord.com/channels/{server_id}/{archive_channel_id}/{archive_message_id}"
        assert item.channel.id == str(channel_id)
        assert item.author.display_name == "target-nick"
        assert item.ai_reason == "Likely spam"
        assert item.ai_categories == ["spam"]
        assert item.confidence is None
        assert item.suggested_action == "warn"

        overview = await build_server_overview(session=session, server_id=server_id)
        assert overview.stats.ai_pending_suggestions == 1
        stream_state = await get_ai_suggestion_stream_state(session=session, server_id=server_id)
        assert stream_state["unread_count"] == 1
        assert stream_state["latest_suggestion_id"] == str(decision_id)

        dismissed = await dismiss_ai_suggestion(
            session=session,
            server_id=server_id,
            suggestion_id=decision_id,
            moderator_user_id=moderator_id,
            body=AIDismissSuggestionModel(reason="false positive"),
        )
        assert dismissed.action_id is None
        assert dismissed.suggestion.status == "dismissed"
        assert dismissed.suggestion.selected_action == "none"
        assert dismissed.suggestion.action_reason == "false positive"
        assert dismissed.suggestion.action_override is True

        decisions = await list_ai_decisions(session=session, server_id=server_id, status_filter="all")
        assert decisions.unread_count == 0
        assert decisions.items[0].status == "dismissed"

        watch_decision_id = uuid4()
        session.add(
            AIModerationDecision(
                id=watch_decision_id,
                server_id=server_id,
                channel_id=channel_id,
                message_id=_make_discord_id(),
                author_user_id=target_id,
                message_content="borderline pattern",
                attachments_json=[],
                provider="fake",
                model="test-model",
                strictness="standard",
                flagged=True,
                severity="low",
                categories=["suspicious_behavior"],
                reason="Monitor for repeat behavior",
                suggested_action="watch",
                rule_ids=[],
                status="pending_review",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

        watched = await approve_ai_suggestion(
            session=session,
            server_id=server_id,
            suggestion_id=watch_decision_id,
            moderator_user_id=moderator_id,
            body=AIApproveSuggestionModel(),
        )
        assert watched.action_id is None
        assert watched.suggestion.status == "action_applied"
        assert watched.suggestion.selected_action == "watch"
        assert watched.suggestion.action_reason == "Monitor for repeat behavior"
        monitored = (
            await session.exec(
                select(MonitoredUser).where(
                    MonitoredUser.server_id == server_id,
                    MonitoredUser.user_id == target_id,
                )
            )
        ).first()
        assert monitored is not None
        assert monitored.source == "ai_moderation"
        assert monitored.reason == "Monitor for repeat behavior"

    await engine.dispose()


def test_ai_moderation_api_service_contracts():
    asyncio.run(_ai_moderation_api_scenario())
