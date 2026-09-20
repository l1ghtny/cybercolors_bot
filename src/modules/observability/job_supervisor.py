"""Recover local loops without coupling their lifecycle to Discord reconnects."""
import asyncio
import logging
from time import monotonic

from prometheus_client import Counter
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger("bot")
JOB_RESTARTS = Counter(
    "cybercolors_background_job_restarts_total",
    "Stopped background loops restarted by the supervisor.",
    ["bot_profile", "job"],
)
RECOVERY_SQLSTATES = {"57P01", "57P02", "57P03", "25006", "53300"}


class RetryableDatabaseError(Exception):
    """A transient database failure eligible for discord.py's retry backoff."""


def is_transient_database_error(error):
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(state, str) and (state.startswith("08") or state in RECOVERY_SQLSTATES):
            return True
        pending.extend(cause for cause in (
            getattr(current, "orig", None), current.__cause__, current.__context__,
        ) if isinstance(cause, BaseException))
    return False


class JobSupervisor:
    def __init__(self, profile, jobs, ready, *, clock=monotonic):
        self.profile, self.jobs, self.ready, self.clock = profile, jobs, ready, clock
        self.task = None
        self.closing = False
        self.retry_at = {}
        self.attempts = {}

    def succeeded(self, name):
        if self.attempts.pop(name, None) is not None:
            logger.info("Background job recovered: profile=%s job=%s", self.profile, name)
        self.retry_at.pop(name, None)

    def check(self):
        if self.closing or not self.ready():
            return
        now = self.clock()
        for job in self.jobs():
            name = job.coro.__name__
            task = job.get_task()
            # Startup owns the first launch. Never duplicate running work or
            # revive an explicitly cancelled task.
            if job.is_running() or task is None or task.cancelled():
                continue
            if name not in self.retry_at:
                attempts = self.attempts.get(name, 0)
                delay = min(30 * 2 ** min(attempts, 4), 300)
                self.retry_at[name] = now + delay
                logger.error(
                    "Background job stopped; restart in %ss: profile=%s job=%s",
                    delay, self.profile, name,
                )
            elif now >= self.retry_at[name]:
                self.retry_at.pop(name)
                self.attempts[name] = self.attempts.get(name, 0) + 1
                # Explicit-time loops wait for their next scheduled occurrence.
                # Restarting does not replay missed birthday announcements.
                job.start()
                JOB_RESTARTS.labels(self.profile, name).inc()

    def start(self):
        if self.task is None:
            for job in self.jobs():
                JOB_RESTARTS.labels(self.profile, job.coro.__name__)
            self.task = asyncio.create_task(self._run(), name="background-job-supervisor")

    async def _run(self):
        while True:
            self.check()
            await asyncio.sleep(5)

    async def close(self):
        self.closing = True
        pending = []
        if self.task is not None:
            self.task.cancel()
            pending.append(self.task)
        for job in self.jobs():
            task = job.get_task()
            if task is not None:
                job.cancel()
                pending.append(task)
        await asyncio.gather(*pending, return_exceptions=True)
