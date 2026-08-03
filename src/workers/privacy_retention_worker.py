from __future__ import annotations

import asyncio
import os

from src.db.database import get_async_session
from src.modules.logs_setup import logger
from src.modules.observability.sentry import configure_sentry
from src.modules.privacy.retention import RetentionSettings, run_retention_batch

log = logger.logging.getLogger("bot")


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def settings_from_env() -> RetentionSettings:
    return RetentionSettings(
        message_content_days=_env_int("MESSAGE_CONTENT_RETENTION_DAYS", 30),
        moderation_evidence_days=_env_int("MODERATION_EVIDENCE_RETENTION_DAYS", 365),
        monitoring_event_days=_env_int("MONITORING_EVENT_RETENTION_DAYS", 90),
        bot_audit_days=_env_int("BOT_AUDIT_RETENTION_DAYS", 90),
        batch_size=_env_int("PRIVACY_RETENTION_BATCH_SIZE", 2_000, maximum=20_000),
    )


async def run_once(settings: RetentionSettings | None = None) -> dict[str, int]:
    async with get_async_session() as session:
        counts = await run_retention_batch(session, settings=settings or settings_from_env())
        await session.commit()
        return counts


async def run_forever() -> None:
    interval_seconds = _env_int("PRIVACY_RETENTION_INTERVAL_SECONDS", 900, minimum=60)
    settings = settings_from_env()
    log.info(
        "Starting privacy retention worker. interval=%ss settings=%s",
        interval_seconds,
        settings,
    )
    while True:
        try:
            counts = await run_once(settings)
            changed = {name: count for name, count in counts.items() if count}
            if changed:
                log.info("Privacy retention pass finished. changes=%s", changed)
        except Exception:
            log.exception("Privacy retention pass failed")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    configure_sentry("privacy-retention-worker")
    asyncio.run(run_forever())
