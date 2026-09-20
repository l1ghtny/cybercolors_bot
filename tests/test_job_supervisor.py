import ast
import asyncio
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import asyncpg
import pytest
from discord.ext import tasks
from sqlalchemy.exc import DBAPIError

from src.modules.observability.job_supervisor import (
    JobSupervisor, RetryableDatabaseError, is_transient_database_error,
)
from src.modules.observability.runtime_status import RuntimeReporter


@pytest.mark.parametrize("error", [
    asyncpg.CannotConnectNowError("database starting"),
    asyncpg.ReadOnlySQLTransactionError("database recovering"),
    asyncpg.ConnectionDoesNotExistError("connection lost"),
    DBAPIError(None, None, asyncpg.CannotConnectNowError("database starting")),
    DBAPIError(None, None, ValueError("lost connection"), connection_invalidated=True),
])
def test_classifies_transient_database_errors(error):
    assert is_transient_database_error(error)


@pytest.mark.parametrize("error", [ValueError("bug"), asyncpg.UniqueViolationError("duplicate"),
                                  asyncpg.InvalidPasswordError("invalid credentials")])
def test_does_not_retry_permanent_errors_as_database_recovery(error):
    assert not is_transient_database_error(error)


def test_exception_chain_cycle_is_bounded():
    error = ValueError("bug")
    error.__cause__ = error
    assert not is_transient_database_error(error)


def stopped_job(name="worker"):
    return SimpleNamespace(coro=SimpleNamespace(__name__=name), is_running=lambda: False,
                           get_task=lambda: SimpleNamespace(cancelled=lambda: False),
                           start=Mock(), cancel=Mock())


def test_restarts_with_capped_backoff_and_resets_only_after_success():
    now = [0]
    job = stopped_job()
    supervisor = JobSupervisor("test", lambda: [job], lambda: True, clock=lambda: now[0])
    for delay in [30, 60, 120, 240, 300, 300]:
        before = job.start.call_count
        supervisor.check()
        now[0] += delay - 1
        supervisor.check()
        assert job.start.call_count == before
        now[0] += 1
        supervisor.check()
        assert job.start.call_count == before + 1
    supervisor.succeeded("worker")
    supervisor.check()
    assert supervisor.retry_at["worker"] == now[0] + 30


def test_does_not_start_before_ready_or_duplicate_running_or_cancelled_work():
    job = stopped_job()
    ready = [False]
    supervisor = JobSupervisor("test", lambda: [job], lambda: ready[0])
    supervisor.check()
    ready[0] = True
    job.get_task = lambda: None
    supervisor.check()
    job.get_task = lambda: SimpleNamespace(cancelled=lambda: True)
    supervisor.check()
    job.get_task = lambda: SimpleNamespace(cancelled=lambda: False)
    job.is_running = lambda: True
    supervisor.check()
    assert supervisor.retry_at == {}
    job.start.assert_not_called()


def tracked_wrapper(client):
    # Exercise the actual decorator without logging in or importing bot startup.
    module = ast.parse(Path("main.py").read_text())
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "report_job_health")
    scope = dict(wraps=wraps, client=client, RetryableDatabaseError=RetryableDatabaseError,
                 is_transient_database_error=is_transient_database_error)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), scope)
    return scope["report_job_health"]


def test_real_loop_retries_wrapped_database_recovery_and_health_stays_failed_until_success(monkeypatch):
    async def scenario():
        recovered = asyncio.Event()
        allow_success = asyncio.Event()
        client = SimpleNamespace(
            shard_count=1, shards={}, guilds=[], guild_presence_synced=True,
            command_sync=SimpleNamespace(state="healthy"),
        )
        jobs = []
        client.job_supervisor = JobSupervisor("retry-test", lambda: jobs, lambda: True)
        client.runtime_status = RuntimeReporter(client, "retry-test", lambda: {"assignments": (jobs, 120)})
        calls = 0

        @tasks.loop(seconds=0.01)
        @tracked_wrapper(client)
        async def gateway_assignment_refresh():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise DBAPIError(None, None, asyncpg.CannotConnectNowError("database starting"))
            await allow_success.wait()
            recovered.set()

        jobs.append(gateway_assignment_refresh)
        gateway_assignment_refresh.add_exception_type(RetryableDatabaseError)
        gateway_assignment_refresh.start()
        try:
            while calls < 2:
                await asyncio.sleep(0)
            assert gateway_assignment_refresh.is_running()
            assert client.runtime_status.snapshot()["components"]["assignments"] == "unavailable"
            allow_success.set()
            await asyncio.wait_for(recovered.wait(), 1)
            await asyncio.sleep(0)
            assert client.runtime_status.snapshot()["components"]["assignments"] == "healthy"
        finally:
            await client.job_supervisor.close()
    monkeypatch.setattr(tasks.ExponentialBackoff, "delay", lambda self: 0)
    asyncio.run(scenario())


def test_failed_real_loop_restarts_and_shutdown_cannot_resurrect_it():
    async def scenario():
        now = [0]
        recovered = asyncio.Event()
        calls = 0

        @tasks.loop(seconds=0.01)
        async def worker():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("unexpected failure")
            recovered.set()

        @worker.error
        async def on_error(error):
            pass

        supervisor = JobSupervisor("restart-test", lambda: [worker], lambda: True, clock=lambda: now[0])
        task = worker.start()
        await asyncio.gather(task, return_exceptions=True)
        assert worker.failed()
        supervisor.check()
        now[0] = 30
        supervisor.check()
        await asyncio.wait_for(recovered.wait(), 1)
        assert worker.is_running()
        await supervisor.close()
        now[0] = 1000
        supervisor.check()
        assert not worker.is_running()
    asyncio.run(scenario())


def test_scheduled_restart_waits_for_next_occurrence():
    async def scenario():
        now = [0]
        calls = 0
        scheduled = (datetime.now(UTC) + timedelta(hours=1)).timetz()

        @tasks.loop(time=scheduled)
        async def birthday():
            nonlocal calls
            calls += 1

        # Simulate a previous failed invocation; retain the real scheduling start.
        failed = asyncio.create_task(asyncio.sleep(0))
        await failed
        birthday._task = failed
        supervisor = JobSupervisor("scheduled-test", lambda: [birthday], lambda: True, clock=lambda: now[0])
        supervisor.check()
        now[0] = 30
        supervisor.check()
        await asyncio.sleep(0)
        assert birthday.is_running()
        assert calls == 0
        await supervisor.close()
    asyncio.run(scenario())
