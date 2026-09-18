import asyncio
import importlib.util
from importlib.metadata import distribution
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from sqlmodel import select

from api.services.monitoring_service import (
    list_monitored_user_status_events,
    maybe_auto_monitor_new_member,
    update_monitored_user,
    upsert_monitored_user,
)
from api.services.server_overview import _monitoring_events
from src.db.database import engine, get_async_session
from src.db.models import (
    GlobalUser,
    MonitoredUser,
    MonitoredUserStatusEvent,
    Server,
    ServerMonitoringSettings,
    ServerSecuritySettings,
    User,
)
from src.modules.moderation import newcomer_restrictions


def _discord_id():
    return 7_200_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _seed(session):
    server_id, target_id, moderator_id = (_discord_id() for _ in range(3))
    session.add(Server(server_id=server_id, server_name="monitoring-regression"))
    for user_id in (target_id, moderator_id):
        session.add(GlobalUser(discord_id=user_id, username=str(user_id)))
    await session.flush()
    for user_id in (target_id, moderator_id):
        session.add(User(server_id=server_id, user_id=user_id, is_member=True))
    await session.flush()
    return server_id, target_id, moderator_id


async def _history_scenario():
    await engine.dispose()
    async with get_async_session() as session:
        server_id, target_id, moderator_id = await _seed(session)
        session.add(ServerMonitoringSettings(
            server_id=server_id, auto_monitor_enabled=True,
            auto_monitor_recent_account_days=7, auto_monitor_no_avatar=True,
        ))
        await session.flush()
        member = SimpleNamespace(
            id=target_id, guild=SimpleNamespace(id=server_id), bot=False,
            created_at=datetime.now(timezone.utc) - timedelta(days=1), avatar=None,
        )
        monitored = await maybe_auto_monitor_new_member(session, member=member)
        assert monitored is not None
        automatic_reason = monitored.reason
        assert "account_age_days=1, no_avatar" in automatic_reason
        await update_monitored_user(
            session, server_id, target_id, "Known community member", False, moderator_id,
        )
        # Manual newcomer reapplication must retain its human actor.
        await upsert_monitored_user(
            session, server_id, target_id, "New report", moderator_id, source="newcomer",
        )
        await update_monitored_user(
            session, server_id, target_id, "Later edit to current context", None, moderator_id,
        )
        events = await _monitoring_events(session, server_id, 100)
        by_reason = {event.description: event for event in events}
        assert set(by_reason) == {automatic_reason, "Known community member", "New report"}
        assert by_reason[automatic_reason].actor is None
        assert by_reason["Known community member"].actor.user_id == str(moderator_id)
        assert by_reason["New report"].actor.user_id == str(moderator_id)
        assert all(event.target.user_id == str(target_id) for event in events)
        statuses = await list_monitored_user_status_events(session, server_id, target_id)
        assert {event.reason for event in statuses} == set(by_reason)
        assert next(event for event in statuses if event.reason == automatic_reason).changed_by is None

        # A legacy event with no saved reason must not borrow today's reason.
        session.add(MonitoredUserStatusEvent(
            monitored_user_id=UUID(monitored.id), from_is_active=True,
            to_is_active=False, reason=None, changed_by_user_id=moderator_id,
        ))
        await session.flush()
        events = await _monitoring_events(session, server_id, 100)
        assert any(event.description is None for event in events)

        # Re-activation through the automatic path also has no human actor.
        await update_monitored_user(session, server_id, target_id, "Closed", False, moderator_id)
        await maybe_auto_monitor_new_member(session, member=member)
        statuses = await list_monitored_user_status_events(session, server_id, target_id)
        automatic_events = [event for event in statuses if event.reason == automatic_reason]
        assert len(automatic_events) == 2
        assert all(event.changed_by is None for event in automatic_events)
        await session.rollback()
    await engine.dispose()


def test_monitoring_log_preserves_reasons_and_manual_or_automatic_actors():
    asyncio.run(_history_scenario())


def test_newcomer_role_activation_is_automatic(monkeypatch):
    settings = ServerSecuritySettings(
        server_id=1, newcomer_restriction_enabled=True,
        newcomer_role_id=10, newcomer_member_role_id=20,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=settings),
        exec=AsyncMock(return_value=SimpleNamespace(first=lambda: None)),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def session_context():
        yield session

    upsert = AsyncMock()
    monkeypatch.setattr(newcomer_restrictions, "get_async_session", session_context)
    monkeypatch.setattr(newcomer_restrictions, "get_or_create_server_record", AsyncMock())
    monkeypatch.setattr(newcomer_restrictions, "get_or_create_user_membership", AsyncMock())
    monkeypatch.setattr(newcomer_restrictions, "upsert_monitored_user", upsert)
    before = SimpleNamespace(roles=[])
    after = SimpleNamespace(
        id=2, bot=False, guild=SimpleNamespace(id=1), nick=None,
        roles=[SimpleNamespace(id=10)],
    )
    assert asyncio.run(newcomer_restrictions.handle_newcomer_role_granted(before, after)) is True
    assert upsert.await_args.kwargs["automatic"] is True
    assert upsert.await_args.kwargs["source"] == "newcomer"


async def _repair_scenario():
    import alembic

    # The repository's migration package shadows the installed Alembic API.
    alembic.__path__.append(str(distribution("alembic").locate_file("alembic")))
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    await engine.dispose()
    path = Path(__file__).resolve().parents[1] / "alembic/versions/394d5143bacf_add_monitoring_log_reasons_release_note.py"
    spec = importlib.util.spec_from_file_location("monitoring_actor_repair", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async with get_async_session() as session:
        server_id, target_id, moderator_id = await _seed(session)
        for source in ("auto", "newcomer", "manual"):
            # Each record needs its own target because monitoring is unique per member.
            if source != "auto":
                target_id = _discord_id()
                session.add(GlobalUser(discord_id=target_id))
                await session.flush()
            monitored = MonitoredUser(
                server_id=server_id, user_id=target_id, added_by_user_id=target_id,
                source=source, reason="Latest mutable context",
            )
            session.add(monitored)
            await session.flush()
            generated_reason = (
                "Automatic newcomer probation after rules acknowledgement"
                if source == "newcomer"
                else "Custom configured reason: account_age_days=1, no_avatar"
            )
            examples = [
                (True, generated_reason, target_id, source != "manual"),
                (True, "Custom configured reason: no_avatar", target_id, source == "auto"),
                (True, "Manual review", target_id, False),
                (True, None, target_id, False),
                (False, generated_reason, target_id, False),
                (True, generated_reason, moderator_id, False),
            ]
            expected = {}
            for active, reason, actor_id, repaired in examples:
                event = MonitoredUserStatusEvent(
                    monitored_user_id=monitored.id, from_is_active=None,
                    to_is_active=active, reason=reason, changed_by_user_id=actor_id,
                )
                session.add(event)
                expected[event.id] = (None if repaired else actor_id, reason)
            await session.flush()
            connection = await session.connection()

            def repair(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    migration._repair_automatic_actors()

            # The repair is safe to run twice and never rewrites reasons.
            await connection.run_sync(repair)
            await connection.run_sync(repair)
            rows = (await session.exec(select(
                MonitoredUserStatusEvent.id, MonitoredUserStatusEvent.changed_by_user_id,
                MonitoredUserStatusEvent.reason,
            ).where(MonitoredUserStatusEvent.monitored_user_id == monitored.id))).all()
            assert {event_id: (actor_id, reason) for event_id, actor_id, reason in rows} == expected
        await session.rollback()
    await engine.dispose()


def test_legacy_actor_repair_is_narrow_and_idempotent():
    asyncio.run(_repair_scenario())
