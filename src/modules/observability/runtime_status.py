"""Bounded, private runtime reports; no message content or Discord credentials."""
import asyncio
import logging
import math
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import httpx
from prometheus_client import Gauge
from sqlalchemy import and_, or_, update
from sqlalchemy.dialects.postgresql import insert

from src.db.database import get_async_session
from src.db.service_status import BotRuntimeStatus, ExternalServiceStatus

logger = logging.getLogger("bot")
RUNTIME_COMPONENT = Gauge("cybercolors_runtime_component_healthy", "Local component health (1 healthy, 0 impaired).", ["bot_profile", "component"])
RUNTIME_REPORT = Gauge("cybercolors_runtime_last_report_timestamp_seconds", "Last successful runtime report.", ["bot_profile"])
SHARD_CONNECTED = Gauge("cybercolors_discord_shard_connected", "Connection health by application shard.", ["bot_profile", "shard"])


async def publish_runtime(profile, process_id, started_at, observed_at, payload):
    table = BotRuntimeStatus.__table__
    statement = insert(table).values(profile=profile, process_id=process_id, started_at=started_at, observed_at=observed_at, payload=payload)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.profile],
        set_={name: getattr(statement.excluded, name) for name in ("process_id", "started_at", "observed_at", "payload")},
        where=or_(table.c.started_at < started_at, and_(table.c.process_id == process_id, table.c.observed_at <= observed_at)),
    )
    async with get_async_session() as session:
        result = await session.execute(statement)
        await session.commit()
        return result.rowcount > 0


def parse_incidents(payload):
    incidents = []
    for item in payload.get("incidents", [])[:10]:
        identifier = item.get("id", "")
        status = item.get("status")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9]{1,40}", identifier):
            continue
        if status not in {"investigating", "identified", "monitoring"}:
            continue
        incidents.append({"title": str(item.get("name", "Discord service incident"))[:200],
                          "url": f"https://discordstatus.com/incidents/{identifier}", "status": status})
    return incidents


async def refresh_discord_status():
    # A shared timestamp claim bounds polling across both bot processes.
    now = datetime.now(UTC)
    async with get_async_session() as session:
        await session.execute(insert(ExternalServiceStatus).values(service="discord", incidents=[]).on_conflict_do_nothing())
        claimed = await session.execute(update(ExternalServiceStatus).where(
            ExternalServiceStatus.service == "discord",
            or_(ExternalServiceStatus.attempted_at.is_(None), ExternalServiceStatus.attempted_at < now - timedelta(seconds=60)),
        ).values(attempted_at=now).returning(ExternalServiceStatus.service))
        should_fetch = claimed.scalar_one_or_none() is not None
        await session.commit()
    if not should_fetch:
        return
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            async with client.stream("GET", "https://discordstatus.com/api/v2/incidents/unresolved.json") as response:
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 128 * 1024:
                        raise ValueError("Discord status response too large")
                import json
                incidents = parse_incidents(json.loads(chunks))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        # Preserve the last successful observation so it can expire honestly.
        return
    async with get_async_session() as session:
        await session.execute(update(ExternalServiceStatus).where(
            ExternalServiceStatus.service == "discord", ExternalServiceStatus.attempted_at == now,
        ).values(observed_at=datetime.now(UTC), incidents=incidents))
        await session.commit()


class RuntimeReporter:
    def __init__(self, client, profile, jobs):
        self.client, self.profile, self.jobs = client, profile, jobs
        self.process_id = str(uuid4())
        self.started_at = datetime.now(UTC)
        self.task = None
        self.server = None
        self.runs = {}
        self.failures = set()
        self.last_states = None
        RUNTIME_REPORT.labels(profile).set(0)

    @contextmanager
    def track_job(self, name):
        self.runs[name] = monotonic()
        try:
            yield
        except BaseException:
            self.failures.add(name)
            raise
        else:
            self.failures.discard(name)
        finally:
            self.runs.pop(name, None)

    def snapshot(self):
        shards = {str(i): "reconnecting" for i in range(self.client.shard_count or 0)}
        for identifier, shard in self.client.shards.items():
            healthy = not shard.is_closed() and math.isfinite(shard.latency)
            shards[str(identifier)] = "healthy" if healthy else "reconnecting"
        for identifier, state in shards.items():
            SHARD_CONNECTED.labels(self.profile, identifier).set(int(state == "healthy"))
        components = {"commands": self.client.command_sync.state}
        for name, (loops, max_runtime) in self.jobs().items():
            loops = list(loops)
            unhealthy = any(not loop.is_running() or loop.failed() for loop in loops)
            job_names = [loop.coro.__name__ for loop in loops]
            overdue = any(job in self.runs and monotonic() - self.runs[job] > max_runtime for job in job_names)
            failed = any(job in self.failures for job in job_names)
            components[name] = "unavailable" if unhealthy or overdue or failed else "healthy"
            if not self.client.guild_presence_synced:
                components[name] = "unknown"
            RUNTIME_COMPONENT.labels(self.profile, name).set(int(components[name] == "healthy"))
        RUNTIME_COMPONENT.labels(self.profile, "commands").set(int(components["commands"] == "healthy"))
        return {"shard_count": self.client.shard_count, "shards": shards, "components": components,
                "guild_ids": [str(guild.id) for guild in self.client.guilds],
                "unavailable_guild_ids": [str(guild.id) for guild in self.client.guilds if guild.unavailable]}

    async def start(self, port=9101):
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="runtime-status-reporter")
            self.server = await asyncio.start_server(self._health_request, "0.0.0.0", port, limit=4096)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _health_request(self, reader, writer):
        try:
            request = await asyncio.wait_for(reader.readline(), 2)
            path = request.split(b" ")[1] if b" " in request else b""
            live = self.task is not None and not self.task.done()
            supervisor = getattr(self.client, "job_supervisor", None)
            if supervisor is not None:
                live = live and supervisor.task is not None and not supervisor.task.done()
            ready = self.client.guild_presence_synced and all(
                value == "healthy" for name, value in self.snapshot()["components"].items() if name != "commands"
            )
            # Liveness depends on our event loop, never on Discord or PostgreSQL.
            healthy = live if path == b"/livez" else live and ready if path == b"/readyz" else False
            status = b"200 OK" if healthy else b"503 Service Unavailable"
            writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except (TimeoutError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    async def _run(self):
        failures = 0
        while True:
            try:
                async with asyncio.timeout(10):
                    snapshot = self.snapshot()
                    accepted = await publish_runtime(self.profile, self.process_id, self.started_at, datetime.now(UTC), snapshot)
                if accepted:
                    RUNTIME_REPORT.labels(self.profile).set(datetime.now(UTC).timestamp())
                states = {"shards": snapshot["shards"], "components": snapshot["components"]}
                if states != self.last_states:
                    logger.info("Runtime service status changed: profile=%s states=%s", self.profile, states)
                    self.last_states = states
                failures = 0
            except Exception:
                failures += 1
                if failures == 1 or failures % 15 == 0:
                    logger.warning("Runtime status report failed; dashboard status will expire.")
            try:
                async with asyncio.timeout(10):
                    await refresh_discord_status()
            except Exception:
                pass
            await asyncio.sleep(20)
