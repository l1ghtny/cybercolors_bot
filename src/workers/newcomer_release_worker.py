import asyncio
import os

from src.db.database import get_async_session
from src.modules.logs_setup import logger
from src.modules.moderation.newcomer_release_worker import process_due_newcomer_releases

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


async def run_once(batch_size: int) -> tuple[int, int]:
    async with get_async_session() as session:
        processed, failed = await process_due_newcomer_releases(session=session, limit=batch_size)
        await session.commit()
        return processed, failed


async def run_forever() -> None:
    interval_seconds = _env_int("NEWCOMER_RELEASE_WORKER_INTERVAL_SECONDS", 60, minimum=5)
    batch_size = _env_int("NEWCOMER_RELEASE_WORKER_BATCH_SIZE", 100, minimum=1, maximum=1000)
    log.info(
        "Starting newcomer release worker. interval=%ss batch_size=%s",
        interval_seconds,
        batch_size,
    )
    while True:
        processed, failed = await run_once(batch_size)
        if processed or failed:
            log.info("Newcomer release worker pass finished. processed=%s failed=%s", processed, failed)
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_forever())
