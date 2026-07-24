import argparse
import asyncio
import os

from src.db.database import get_async_session
from src.modules.ai.youtube_channel_sync import sync_due_youtube_channel_once


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


async def _run_batch(batch_size: int) -> int:
    processed = 0
    async with get_async_session() as session:
        for _ in range(batch_size):
            if not await sync_due_youtube_channel_once(session):
                break
            processed += 1
        await session.commit()
    return processed


async def _run_worker(*, once: bool, poll_seconds: int, batch_size: int) -> None:
    while True:
        processed = await _run_batch(batch_size)
        print(f"youtube_channels_processed={processed}", flush=True)
        if once:
            return
        if processed == 0:
            await asyncio.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize subscribed YouTube channels.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=_env_int("AI_YOUTUBE_CHANNEL_WORKER_POLL_SECONDS", 60),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_env_int("AI_YOUTUBE_CHANNEL_WORKER_BATCH_SIZE", 5),
    )
    args = parser.parse_args()
    asyncio.run(
        _run_worker(
            once=args.once,
            poll_seconds=max(args.poll_seconds, 1),
            batch_size=max(args.batch_size, 1),
        )
    )


if __name__ == "__main__":
    main()
