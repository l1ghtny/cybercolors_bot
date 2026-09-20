from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.service_status import DiscordIncident, ServerServiceStatus, ServiceComponent
from src.db.models import Server
from src.db.service_status import BotRuntimeStatus, ExternalServiceStatus

COMPONENT_IDS = ("gateway", "assignments", "commands", "moderation_expiry", "birthdays")
REPORT_TTL = timedelta(seconds=90)
ADVISORY_TTL = timedelta(minutes=5)
VALID_STATES = {"healthy", "reconnecting", "retrying", "unavailable", "unknown"}


def summarize_status(server_id: int, runtime: BotRuntimeStatus | None, advisory: ExternalServiceStatus | None, now: datetime) -> ServerServiceStatus:
    components = [ServiceComponent(id=name, state="unknown", reason="stale_report") for name in COMPONENT_IDS]
    result = ServerServiceStatus(state="unknown", server_time=now, components=components)
    if advisory and advisory.observed_at and timedelta(0) <= now - advisory.observed_at <= ADVISORY_TTL:
        result.discord_status_observed_at = advisory.observed_at
        if advisory.incidents:
            result.discord_incident = DiscordIncident.model_validate(advisory.incidents[0])
    if runtime is None:
        return result
    result.observed_at = runtime.observed_at
    result.expires_at = runtime.observed_at + REPORT_TTL
    if now >= result.expires_at or runtime.observed_at > now + timedelta(seconds=30):
        return result
    payload = runtime.payload
    shard_count = payload.get("shard_count", 0)
    if not isinstance(shard_count, int) or shard_count <= 0:
        return result
    shard_id = (server_id >> 22) % shard_count
    gateway = payload.get("shards", {}).get(str(shard_id), "unknown")
    if str(server_id) not in payload.get("guild_ids", []):
        gateway = "unknown"
    elif str(server_id) in payload.get("unavailable_guild_ids", []):
        gateway = "unavailable"
    states = {**payload.get("components", {}), "gateway": gateway}
    for component in components:
        value = states.get(component.id, "unknown")
        component.state = value if value in VALID_STATES else "unknown"
        component.reason = None
    if gateway in {"reconnecting", "unavailable"}:
        result.state = "reconnecting"
    elif any(c.state in {"unavailable", "retrying"} for c in components):
        result.state = "degraded"
    elif any(c.state != "healthy" for c in components):
        result.state = "unknown"
    else:
        result.state = "healthy"
    return result


async def get_server_service_status(session: AsyncSession, server_id: int) -> ServerServiceStatus:
    server = await session.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "Server not found")
    runtime = await session.get(BotRuntimeStatus, server.bot_profile)
    advisory = await session.get(ExternalServiceStatus, "discord")
    return summarize_status(server_id, runtime, advisory, datetime.now(UTC))
