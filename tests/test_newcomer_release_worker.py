import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlmodel import select

from src.db.database import engine, get_async_session
from src.db.models import (
    GlobalUser,
    MonitoredUser,
    MonitoredUserStatusEvent,
    Server,
    ServerSecuritySettings,
    User,
)
from src.modules.moderation.newcomer_release_worker import process_due_newcomer_releases


def _make_discord_id() -> int:
    return 9_300_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _insert_newcomer(*, lockdown_enabled: bool = False):
    server_id = _make_discord_id()
    user_id = _make_discord_id()
    newcomer_role_id = _make_discord_id()
    member_role_id = _make_discord_id()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="newcomer-worker", bot_active=True))
        session.add(GlobalUser(discord_id=user_id, username="newcomer"))
        await session.flush()
        session.add(User(server_id=server_id, user_id=user_id, server_nickname="newcomer", is_member=True))
        session.add(
            ServerSecuritySettings(
                server_id=server_id,
                newcomer_role_id=newcomer_role_id,
                newcomer_member_role_id=member_role_id,
                newcomer_restriction_enabled=True,
                newcomer_auto_release_minutes=60,
                lockdown_enabled=lockdown_enabled,
            )
        )
        await session.flush()
        item = MonitoredUser(
            server_id=server_id,
            user_id=user_id,
            added_by_user_id=user_id,
            reason="Automatic newcomer restriction",
            source="newcomer",
            release_due_at=now - timedelta(minutes=1),
            is_active=True,
        )
        session.add(item)
        await session.commit()
    return server_id, user_id, newcomer_role_id, member_role_id, now


async def _release_worker_scenario(monkeypatch) -> None:
    import src.modules.moderation.newcomer_release_worker as worker

    await engine.dispose()
    server_id, user_id, newcomer_role_id, member_role_id, now = await _insert_newcomer()
    promotions: list[dict] = []

    async def fake_fetch_guild_member(received_server_id: int, received_user_id: int) -> dict:
        assert received_server_id == server_id
        assert received_user_id == user_id
        return {"user": {"id": str(user_id)}, "roles": [str(newcomer_role_id)]}

    async def fake_promote_newcomer_member(**kwargs) -> None:
        promotions.append(kwargs)

    monkeypatch.setattr(worker, "fetch_guild_member", fake_fetch_guild_member)
    monkeypatch.setattr(worker, "promote_newcomer_member", fake_promote_newcomer_member)

    async with get_async_session() as session:
        processed, failed = await process_due_newcomer_releases(session=session, now=now, limit=10)
        await session.commit()

        assert (processed, failed) == (1, 0)
        assert len(promotions) == 1
        assert promotions[0]["server_id"] == server_id
        assert promotions[0]["user_id"] == user_id
        assert promotions[0]["current_role_ids"] == {newcomer_role_id}
        assert promotions[0]["settings"].newcomer_member_role_id == member_role_id

        item = (
            await session.exec(
                select(MonitoredUser).where(
                    MonitoredUser.server_id == server_id,
                    MonitoredUser.user_id == user_id,
                )
            )
        ).one()
        assert item.is_active is False
        assert item.released_at == now
        assert item.release_error is None

        status_events = (
            await session.exec(
                select(MonitoredUserStatusEvent).where(
                    MonitoredUserStatusEvent.monitored_user_id == item.id,
                    MonitoredUserStatusEvent.to_is_active.is_(False),
                )
            )
        ).all()
        assert len(status_events) == 1

    await engine.dispose()


async def _lockdown_skip_scenario(monkeypatch) -> None:
    import src.modules.moderation.newcomer_release_worker as worker

    await engine.dispose()
    server_id, user_id, _newcomer_role_id, _member_role_id, now = await _insert_newcomer(lockdown_enabled=True)

    async def fake_fetch_guild_member(received_server_id: int, received_user_id: int) -> dict:
        raise AssertionError("worker should not fetch members while lockdown is enabled")

    monkeypatch.setattr(worker, "fetch_guild_member", fake_fetch_guild_member)

    async with get_async_session() as session:
        processed, failed = await process_due_newcomer_releases(session=session, now=now, limit=10)
        await session.commit()

        assert (processed, failed) == (0, 0)
        item = (
            await session.exec(
                select(MonitoredUser).where(
                    MonitoredUser.server_id == server_id,
                    MonitoredUser.user_id == user_id,
                )
            )
        ).one()
        assert item.is_active is True
        assert item.released_at is None

    await engine.dispose()


def test_newcomer_release_worker_promotes_member_and_marks_monitoring_inactive(monkeypatch):
    asyncio.run(_release_worker_scenario(monkeypatch))


def test_newcomer_release_worker_skips_lockdown(monkeypatch):
    asyncio.run(_lockdown_skip_scenario(monkeypatch))
