import asyncio
import logging
import os

import discord
from sqlmodel import select

from src.db.database import get_async_session, log_pool_status
from src.db.models import DeletedMessage
from src.modules.moderation.moderation_helpers import ensure_message_foreign_keys, log_message
from src.modules.monitoring.activity import record_message_activity

logger = logging.getLogger(__name__)

_QUEUE_MAX_SIZE = int(os.getenv("MESSAGE_INGESTION_QUEUE_MAX_SIZE", "5000"))
_WORKER_COUNT = int(os.getenv("MESSAGE_INGESTION_WORKERS", "2"))
_WARN_EVERY_DROPS = int(os.getenv("MESSAGE_INGESTION_WARN_EVERY_DROPS", "100"))
_METRICS_EVERY_MESSAGES = int(os.getenv("MESSAGE_INGESTION_METRICS_EVERY_MESSAGES", "1000"))

_queue: asyncio.Queue[discord.Message] | None = None
_workers: list[asyncio.Task] = []
_dropped_count = 0
_processed_count = 0


def _queue_or_create() -> asyncio.Queue[discord.Message]:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=max(1, _QUEUE_MAX_SIZE))
    return _queue


def start_message_ingestion_workers() -> None:
    queue = _queue_or_create()
    live_workers = [worker for worker in _workers if not worker.done()]
    _workers[:] = live_workers
    missing = max(0, _WORKER_COUNT - len(_workers))
    for _ in range(missing):
        worker_id = len(_workers) + 1
        _workers.append(asyncio.create_task(_message_ingestion_worker(worker_id, queue)))
    if missing:
        logger.info(
            "Started %s message ingestion worker(s); total=%s queue_max_size=%s",
            missing,
            len(_workers),
            queue.maxsize,
        )


def enqueue_message_ingestion(message: discord.Message) -> bool:
    global _dropped_count
    queue = _queue_or_create()
    try:
        queue.put_nowait(message)
        return True
    except asyncio.QueueFull:
        _dropped_count += 1
        if _dropped_count == 1 or _dropped_count % max(1, _WARN_EVERY_DROPS) == 0:
            logger.warning(
                "Message ingestion queue full; dropped non-critical archival work. dropped=%s queue_size=%s queue_max_size=%s",
                _dropped_count,
                queue.qsize(),
                queue.maxsize,
            )
            log_pool_status(logger, "message_ingestion_queue_full")
        return False


async def _message_ingestion_worker(worker_id: int, queue: asyncio.Queue[discord.Message]) -> None:
    global _processed_count
    logger.info("Message ingestion worker %s started", worker_id)
    while True:
        message = await queue.get()
        try:
            await _archive_message(message)
            await record_message_activity(message)
            _processed_count += 1
            if _processed_count % max(1, _METRICS_EVERY_MESSAGES) == 0:
                logger.info(
                    "Message ingestion metrics processed=%s dropped=%s queue_size=%s",
                    _processed_count,
                    _dropped_count,
                    queue.qsize(),
                )
                log_pool_status(logger, "message_ingestion_periodic")
        except Exception:
            logger.exception(
                "Message ingestion failed for message_id=%s server_id=%s channel_id=%s",
                getattr(message, "id", None),
                getattr(getattr(message, "guild", None), "id", None),
                getattr(getattr(message, "channel", None), "id", None),
            )
            log_pool_status(logger, "message_ingestion_error")
        finally:
            queue.task_done()


async def _archive_message(message: discord.Message) -> None:
    if message.guild is None or getattr(message.author, "bot", False):
        return
    async with get_async_session() as session:
        deleted_result = await session.exec(
            select(DeletedMessage.id).where(DeletedMessage.message_id == message.id).limit(1)
        )
        if deleted_result.first() is not None:
            return
        await ensure_message_foreign_keys(message, session)
        await log_message(message, session)
        await session.commit()
