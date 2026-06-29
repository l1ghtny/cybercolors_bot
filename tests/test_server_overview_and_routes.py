import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from starlette.routing import Match

from api.api_main import app
from api.services.server_overview import build_server_overview, build_server_timeline
from src.db.database import engine, get_async_session
from src.db.models import (
    ActionType,
    Birthday,
    CaseStatus,
    DeletedMessage,
    EvidenceType,
    GlobalUser,
    MessageLog,
    ModerationAction,
    ModerationCase,
    ModerationCaseEvidence,
    ModerationCaseNote,
    ModerationRule,
    MonitoredUser,
    MonitoredUserStatusEvent,
    Replies,
    Server,
    ServerLocalizationSettings,
    ServerModerationSettings,
    ServerSecuritySettings,
    User,
)


def _make_discord_id() -> int:
    return 9_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_deleted_message_action_route_uses_static_prefix_before_generic_action_details():
    path = "/moderation/actions/deleted-messages/11111111-1111-1111-1111-111111111111"
    scope = {"type": "http", "method": "GET", "path": path}

    for route in app.routes:
        match, child_scope = route.matches(scope)
        if match == Match.FULL:
            assert route.path == "/moderation/actions/deleted-messages/{action_id}"
            assert child_scope["path_params"] == {"action_id": "11111111-1111-1111-1111-111111111111"}
            return

    raise AssertionError("deleted message action route did not match")


async def _overview_and_timeline_scenario() -> None:
    await engine.dispose()
    now = _naive_now()
    server_id = _make_discord_id()
    moderator_id = _make_discord_id()
    target_id = _make_discord_id()
    reply_id = uuid4()
    case_id = uuid4()
    action_id = uuid4()
    monitored_id = uuid4()

    async with get_async_session() as session:
        session.add(
            Server(
                server_id=server_id,
                server_name="overview-server",
                birthday_channel_id=_make_discord_id(),
                birthday_role_id=_make_discord_id(),
                bot_active=True,
            )
        )
        session.add(GlobalUser(discord_id=moderator_id, username="moderator"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        session.add(User(user_id=moderator_id, server_id=server_id, server_nickname="mod", is_member=True))
        session.add(User(user_id=target_id, server_id=server_id, server_nickname="target-nick", is_member=True))
        await session.flush()
        session.add(Birthday(user_id=target_id, day=1, month=1))
        session.add(ServerModerationSettings(server_id=server_id, mute_role_id=_make_discord_id(), mod_log_channel_id=_make_discord_id()))
        session.add(ServerSecuritySettings(server_id=server_id, verified_role_id=_make_discord_id(), lockdown_enabled=True))
        session.add(ServerLocalizationSettings(server_id=server_id, locale_code="ru"))
        session.add(Replies(id=reply_id, bot_reply="hello", server_id=server_id, created_by_id=moderator_id, created_at=now))
        session.add(ModerationRule(id=uuid4(), server_id=server_id, title="No spam", is_active=True, created_by_user_id=moderator_id))
        session.add(
            MessageLog(
                message_id=_make_discord_id(),
                user_id=target_id,
                channel_id=_make_discord_id(),
                content="message",
                created_at=now,
                server_id=server_id,
            )
        )
        session.add(
            DeletedMessage(
                server_id=server_id,
                message_id=_make_discord_id(),
                channel_id=_make_discord_id(),
                author_user_id=target_id,
                content="deleted",
                deleted_at=now,
            )
        )
        session.add(
            ModerationCase(
                id=case_id,
                server_id=server_id,
                target_user_id=target_id,
                opened_by_user_id=moderator_id,
                title="Case title",
                status=CaseStatus.OPEN,
                created_at=now,
            )
        )
        session.add(
            ModerationAction(
                id=action_id,
                action_type=ActionType.MUTE,
                server_id=server_id,
                target_user_id=target_id,
                moderator_user_id=moderator_id,
                reason="Muted for test",
                case_id=case_id,
                created_at=now,
                is_active=True,
            )
        )
        session.add(
            ModerationCaseNote(
                case_id=case_id,
                author_user_id=moderator_id,
                note="case note",
                created_at=now,
            )
        )
        session.add(
            ModerationCaseEvidence(
                case_id=case_id,
                added_by_user_id=moderator_id,
                evidence_type=EvidenceType.NOTE,
                text="evidence",
                created_at=now,
            )
        )
        session.add(
            MonitoredUser(
                id=monitored_id,
                server_id=server_id,
                user_id=target_id,
                added_by_user_id=moderator_id,
                reason="watch",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MonitoredUserStatusEvent(
                monitored_user_id=monitored_id,
                changed_by_user_id=moderator_id,
                from_is_active=None,
                to_is_active=True,
                changed_at=now,
            )
        )
        await session.commit()

    async with get_async_session() as session:
        overview = await build_server_overview(session=session, server_id=server_id)
        assert overview.stats.moderation_actions_today == 1
        assert overview.stats.open_cases == 1
        assert overview.stats.active_mutes == 1
        assert overview.stats.active_monitored_users == 1
        assert overview.stats.deleted_messages_today == 1
        assert overview.stats.replies_count == 1
        assert overview.stats.active_rules_count == 1
        assert overview.stats.birthdays_count == 1
        assert overview.stats.messages_today == 1
        assert overview.stats.active_users_today == 1
        assert overview.setup.mute_role_configured is True
        assert overview.setup.mod_log_channel_configured is True
        assert overview.setup.birthday_channel_configured is True
        assert overview.setup.birthday_role_configured is True
        assert overview.setup.verified_role_configured is True
        assert overview.setup.lockdown_enabled is True
        assert overview.setup.locale_code == "ru"

        timeline = await build_server_timeline(session=session, server_id=server_id, limit=20)
        event_types = {event.event_type for event in timeline.events}
        assert "moderation_action_created" in event_types
        assert "moderation_case_opened" in event_types
        assert "monitored_user_status_changed" in event_types
        assert "moderation_case_note_added" in event_types
        assert "moderation_case_evidence_added" in event_types

    await engine.dispose()


def test_server_overview_and_timeline_contracts():
    asyncio.run(_overview_and_timeline_scenario())