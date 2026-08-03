import asyncio
import os

from src.db.database import get_async_session
from src.modules.logs_setup import logger
from src.modules.observability.sentry import configure_sentry
from api.services.scheduled_posts import (
    claim_due_scheduled_post,
    deliver_claimed_scheduled_post,
)

log = logger.logging.getLogger("bot")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


async def run_once(batch_size: int) -> int:
    processed = 0
    for _ in range(batch_size):
        async with get_async_session() as session:
            claimed = await claim_due_scheduled_post(session)
            await session.commit()
            if claimed is None:
                break
            post, run = claimed
            await deliver_claimed_scheduled_post(session, post=post, run=run)
            processed += 1
    return processed


async def run_forever() -> None:
    interval_seconds = _env_int(
        "SCHEDULED_POSTS_WORKER_INTERVAL_SECONDS", 10, minimum=2, maximum=300
    )
    batch_size = _env_int("SCHEDULED_POSTS_WORKER_BATCH_SIZE", 25, minimum=1, maximum=200)
    log.info(
        "Starting scheduled posts worker. interval=%ss batch_size=%s",
        interval_seconds,
        batch_size,
    )
    while True:
        try:
            processed = await run_once(batch_size)
            if processed:
                log.info("Scheduled posts worker pass finished. processed=%s", processed)
        except Exception:
            log.exception("Scheduled posts worker pass failed")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    configure_sentry("scheduled-posts-worker")
    asyncio.run(run_forever())
