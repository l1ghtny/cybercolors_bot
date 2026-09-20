import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.services.service_status import get_server_service_status, summarize_status
from src.db.models import Server
from src.db.service_status import BotRuntimeStatus, ExternalServiceStatus
from src.modules.observability.runtime_status import RuntimeReporter, parse_incidents

NOW = datetime(2026, 9, 16, tzinfo=UTC)
GUILD_A = 2 << 22
GUILD_B = 3 << 22


def report(**changes):
    values = dict(profile="modral", process_id="test", started_at=NOW - timedelta(hours=1), observed_at=NOW,
                  payload={"shard_count": 2, "shards": {"0": "healthy", "1": "reconnecting"},
                           "guild_ids": [str(GUILD_A), str(GUILD_B)], "unavailable_guild_ids": [],
                           "components": {name: "healthy" for name in ("commands", "assignments", "birthdays", "moderation_expiry")}})
    values.update(changes)
    return BotRuntimeStatus(**values)


def test_only_affected_shard_is_reconnecting():
    result = summarize_status(GUILD_A, report(), None, NOW)
    assert result.state == "healthy"
    assert result.server_time == NOW
    assert summarize_status(GUILD_A, None, None, NOW).server_time == NOW
    assert summarize_status(GUILD_B, report(), None, NOW).state == "reconnecting"


@pytest.mark.parametrize("offset", [-90, -1000, 31])
def test_stale_or_future_runtime_is_unknown(offset):
    result = summarize_status(GUILD_A, report(observed_at=NOW + timedelta(seconds=offset)), None, NOW)
    assert result.state == "unknown"
    assert all(c.state == "unknown" for c in result.components)


def test_vendor_incident_is_separate_and_expires():
    advisory = ExternalServiceStatus(service="discord", observed_at=NOW, incidents=[{"title": "API errors", "url": "https://discordstatus.com/incidents/abc", "status": "investigating"}])
    result = summarize_status(GUILD_A, report(), advisory, NOW)
    assert result.state == "healthy"
    assert result.discord_incident.title == "API errors"
    assert summarize_status(GUILD_A, None, advisory, NOW + timedelta(minutes=6)).discord_incident is None


@pytest.mark.parametrize("component", ["commands", "birthdays", "moderation_expiry", "assignments"])
def test_stopped_component_is_partial_failure(component):
    runtime = report()
    runtime.payload["components"][component] = "unavailable"
    assert summarize_status(GUILD_A, runtime, None, NOW).state == "degraded"


def test_unavailable_guild_and_absent_guild_are_not_healthy():
    runtime = report()
    runtime.payload["unavailable_guild_ids"] = [str(GUILD_A)]
    assert summarize_status(GUILD_A, runtime, None, NOW).state == "reconnecting"
    assert summarize_status(4 << 22, runtime, None, NOW).state == "unknown"


def test_server_profile_selects_only_its_own_runtime():
    async def scenario():
        session = SimpleNamespace(get=AsyncMock(side_effect=[Server(server_id=GUILD_A, bot_profile="cybercolors"), report(), None]))
        await get_server_service_status(session, GUILD_A)
        assert session.get.await_args_list[1].args == (BotRuntimeStatus, "cybercolors")
    asyncio.run(scenario())


@pytest.mark.parametrize("denial", [401, 403, 409, 503])
def test_endpoint_fails_closed_before_reading_status(monkeypatch, denial):
    from api.routers import servers as routes
    from api.dependencies.server_access import require_server_dashboard_access
    from src.db.database import get_session
    app = FastAPI()
    app.include_router(routes.servers)
    async def deny():
        raise HTTPException(denial, "Access cannot be verified")
    app.dependency_overrides[require_server_dashboard_access] = deny
    app.dependency_overrides[get_session] = lambda: object()
    read = AsyncMock()
    monkeypatch.setattr(routes, "get_server_service_status", read)
    response = TestClient(app).get(f"/servers/{GUILD_A}/service-status")
    assert response.status_code == denial
    read.assert_not_awaited()


def test_endpoint_response_excludes_internal_runtime_fields(monkeypatch):
    from api.routers import servers as routes
    from api.dependencies.server_access import require_server_dashboard_access
    from src.db.database import get_session
    app = FastAPI()
    app.include_router(routes.servers)
    app.dependency_overrides[require_server_dashboard_access] = lambda: 42
    app.dependency_overrides[get_session] = lambda: object()
    monkeypatch.setattr(routes, "get_server_service_status", AsyncMock(return_value=summarize_status(GUILD_A, report(), None, NOW)))
    response = TestClient(app).get(f"/servers/{GUILD_A}/service-status")
    assert response.status_code == 200
    assert response.json()["server_time"] == "2026-09-16T00:00:00Z"
    assert "process_id" not in response.text
    assert "guild_ids" not in response.text
    assert len(response.json()["components"]) == 5
    assert response.headers["cache-control"] == "private, no-store"


def reporter():
    client = SimpleNamespace(shard_count=2, shards={0: SimpleNamespace(is_closed=lambda: False, latency=0.05)},
                             command_sync=SimpleNamespace(state="retrying"), guild_presence_synced=True,
                             guilds=[SimpleNamespace(id=GUILD_A, unavailable=False)])
    loop = SimpleNamespace(is_running=lambda: True, failed=lambda: False, coro=SimpleNamespace(__name__="birthday"))
    return RuntimeReporter(client, "test", lambda: {"birthdays": ([loop], 10)}), loop


def test_scheduled_loop_between_runs_is_healthy_but_stuck_or_failed_run_is_not(monkeypatch):
    runtime, loop = reporter()
    assert runtime.snapshot()["components"]["birthdays"] == "healthy"
    monkeypatch.setattr("src.modules.observability.runtime_status.monotonic", lambda: 100)
    runtime.runs["birthday"] = 80
    assert runtime.snapshot()["components"]["birthdays"] == "unavailable"
    runtime.runs.clear()
    with pytest.raises(ValueError), runtime.track_job("birthday"):
        raise ValueError("temporary task failure")
    assert runtime.snapshot()["components"]["birthdays"] == "unavailable"
    with runtime.track_job("birthday"):
        pass
    assert runtime.snapshot()["components"]["birthdays"] == "healthy"
    loop.is_running = lambda: False
    assert runtime.snapshot()["components"]["birthdays"] == "unavailable"


def test_startup_is_unknown_and_disconnected_shards_never_green():
    runtime, _ = reporter()
    runtime.client.guild_presence_synced = False
    snapshot = runtime.snapshot()
    assert snapshot["components"]["birthdays"] == "unknown"
    assert snapshot["shards"] == {"0": "healthy", "1": "reconnecting"}


def test_vendor_links_are_canonical_and_resolved_incidents_are_excluded():
    assert parse_incidents({"incidents": [
        {"id": "abc123", "name": "API error", "status": "investigating", "shortlink": "https://evil.test"},
        {"id": "def456", "status": "resolved"}, {"id": "../invalid", "status": "identified"},
    ]}) == [{"title": "API error", "url": "https://discordstatus.com/incidents/abc123", "status": "investigating"}]


def test_liveness_does_not_depend_on_discord_and_readiness_detects_stopped_worker():
    async def scenario():
        from unittest.mock import Mock
        runtime, loop = reporter()
        runtime.task = SimpleNamespace(done=lambda: False)
        runtime.client.shards = {}
        async def probe(path):
            reader = asyncio.StreamReader()
            reader.feed_data(f"GET {path} HTTP/1.1\r\n".encode())
            writer = SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock())
            await runtime._health_request(reader, writer)
            return writer.write.call_args.args[0]
        assert b"200 OK" in await probe("/livez")
        assert b"200 OK" in await probe("/readyz")  # Command registration is still retrying.
        loop.is_running = lambda: False
        assert b"200 OK" in await probe("/livez")
        assert b"503" in await probe("/readyz")
        runtime.task = SimpleNamespace(done=lambda: True)
        assert b"503" in await probe("/livez")
    asyncio.run(scenario())


def test_assignment_failure_does_not_claim_discord_is_disconnected():
    runtime = report()
    runtime.payload["components"]["assignments"] = "unavailable"
    status = summarize_status(GUILD_A, runtime, None, NOW)
    assert status.state == "degraded"
    states = {component.id: component.state for component in status.components}
    assert states["gateway"] == "healthy"
    assert states["assignments"] == "unavailable"


def test_liveness_detects_stopped_supervisor():
    async def scenario():
        from unittest.mock import Mock
        runtime, _ = reporter()
        runtime.task = SimpleNamespace(done=lambda: False)
        runtime.client.job_supervisor = SimpleNamespace(task=SimpleNamespace(done=lambda: True))
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /livez HTTP/1.1\r\n")
        writer = SimpleNamespace(write=Mock(), drain=AsyncMock(), close=Mock())
        await runtime._health_request(reader, writer)
        assert b"503" in writer.write.call_args.args[0]
    asyncio.run(scenario())
