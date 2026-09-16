import asyncio
from datetime import UTC, datetime, timedelta

from src.db.database import engine, get_async_session
from src.db.service_status import BotRuntimeStatus
from src.modules.observability.runtime_status import publish_runtime


def test_replacement_process_fences_old_reports_across_independent_sessions():
    async def scenario():
        await engine.dispose()
        now = datetime.now(UTC)
        await publish_runtime("test-fencing", "old", now, now, {"version": "old"})
        await publish_runtime("test-fencing", "new", now + timedelta(seconds=1), now + timedelta(seconds=1), {"version": "new"})
        await publish_runtime("test-fencing", "old", now, now + timedelta(seconds=2), {"version": "old-late"})
        await publish_runtime("test-fencing", "new", now + timedelta(seconds=1), now, {"version": "out-of-order"})
        async with get_async_session() as session:
            row = await session.get(BotRuntimeStatus, "test-fencing")
            assert row.process_id == "new"
            assert row.payload == {"version": "new"}
        await engine.dispose()
    asyncio.run(scenario())


def test_shared_advisory_claim_limits_fetches_and_failed_fetch_preserves_observation(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from src.db.service_status import ExternalServiceStatus
    from src.modules.observability.runtime_status import refresh_discord_status
    import httpx
    from sqlalchemy import update

    async def scenario():
        await engine.dispose()
        now = datetime.now(UTC)
        async with get_async_session() as session:
            session.add(ExternalServiceStatus(service="discord", observed_at=now, incidents=[{"title": "Known incident"}]))
            await session.commit()
        failing_client = Mock(side_effect=httpx.ConnectError("unavailable"))
        monkeypatch.setattr("src.modules.observability.runtime_status.httpx.AsyncClient", failing_client)
        await asyncio.gather(refresh_discord_status(), refresh_discord_status())
        assert failing_client.call_count == 1
        async with get_async_session() as session:
            row = await session.get(ExternalServiceStatus, "discord")
            assert row.observed_at == now
            assert row.incidents == [{"title": "Known incident"}]
            assert row.attempted_at >= now
        await engine.dispose()
    asyncio.run(scenario())
