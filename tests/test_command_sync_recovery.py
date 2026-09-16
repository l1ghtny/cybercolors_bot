import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import discord
import pytest

from src.commands.sync import BackgroundCommandSync


def http_error(status):
    return discord.HTTPException(SimpleNamespace(status=status, reason="test"), "test")


@pytest.mark.parametrize("error", [http_error(500), http_error(503), http_error(429), OSError(), aiohttp.ClientError(), TimeoutError()])
def test_temporary_failure_retries_once_and_stops_after_success(monkeypatch, error):
    async def scenario():
        sleep = AsyncMock()
        monkeypatch.setattr("src.commands.sync.asyncio.sleep", sleep)
        sync = AsyncMock(side_effect=[error, None])
        ready = AsyncMock()
        runner = BackgroundCommandSync(sync, ready)
        runner.start()
        assert runner.state == "retrying"
        task = runner._task
        runner.start()
        assert runner._task is task
        await task
        runner.start()
        assert runner._task is task
        assert runner.state == "healthy"
        assert sync.await_count == ready.await_count == 2
        sleep.assert_awaited_once_with(5)
        await runner.close()

    asyncio.run(scenario())


def test_retry_delay_is_capped(monkeypatch):
    async def scenario():
        sleep = AsyncMock()
        monkeypatch.setattr("src.commands.sync.asyncio.sleep", sleep)
        runner = BackgroundCommandSync(AsyncMock(side_effect=[http_error(503)] * 9 + [None]), AsyncMock())
        runner.start()
        await runner._task
        assert [call.args[0] for call in sleep.await_args_list] == [5, 10, 20, 40, 80, 160, 300, 300, 300]

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [http_error(400), http_error(403), ValueError("bad command")])
def test_permanent_failure_is_reported_without_retry(monkeypatch, error):
    async def scenario():
        sleep = AsyncMock()
        monkeypatch.setattr("src.commands.sync.asyncio.sleep", sleep)
        report_error = Mock()
        monkeypatch.setattr("src.commands.sync.logger.exception", report_error)
        sync = AsyncMock(side_effect=error)
        runner = BackgroundCommandSync(sync, AsyncMock())
        runner.start()
        await runner._task
        runner.start()
        assert runner.state == "unavailable"
        sync.assert_awaited_once()
        sleep.assert_not_awaited()
        report_error.assert_called_once()
        assert "needs operator attention" in report_error.call_args.args[0]

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["ready", "sync", "backoff"])
def test_shutdown_cancels_pending_registration(monkeypatch, phase):
    async def scenario():
        entered = asyncio.Event()

        async def block(*args):
            entered.set()
            await asyncio.Event().wait()

        sync = AsyncMock(side_effect=block if phase == "sync" else http_error(503))
        ready = AsyncMock(side_effect=block if phase == "ready" else None)
        if phase == "backoff":
            monkeypatch.setattr("src.commands.sync.asyncio.sleep", block)
        runner = BackgroundCommandSync(sync, ready)
        runner.start()
        await asyncio.wait_for(entered.wait(), timeout=1)
        await runner.close()
        assert runner._task.cancelled()

    asyncio.run(scenario())


def test_ready_starts_workers_while_discord_registration_is_still_failing(monkeypatch):
    # Execute the real handler without importing main.py, which logs in to Discord.
    module = ast.parse((Path(__file__).parents[1] / "main.py").read_text())
    client_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Aclient")
    handler = next(node for node in client_class.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_ready")

    async def scenario():
        retry_wait = asyncio.Event()

        async def backoff(_delay):
            retry_wait.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("src.commands.sync.asyncio.sleep", backoff)
        workers = {}
        for name in ("gateway_assignment_refresh", "birthday", "check_users_with_birthdays", "auto_unmute_worker"):
            worker = SimpleNamespace(running=False)
            worker.is_running = lambda worker=worker: worker.running
            worker.start = Mock(side_effect=lambda worker=worker: setattr(worker, "running", True))
            workers[name] = worker
        namespace = {
            **workers,
            "DISCORD_GATEWAY_STATUS": Mock(),
            "sync_active_guild_presence": AsyncMock(),
            "BOT_PROFILE": "cybercolors",
            "logger": Mock(),
        }
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "main.py", "exec"), namespace)
        client = SimpleNamespace(
            wait_until_ready=AsyncMock(), added=False, guild_presence_synced=False,
            guilds=[], refresh_primary_guild_assignments=AsyncMock(), user="test",
        )
        sync = AsyncMock(side_effect=http_error(500))
        client.command_sync = BackgroundCommandSync(sync, client.wait_until_ready)
        await asyncio.wait_for(namespace["on_ready"](client), timeout=1)
        await asyncio.wait_for(retry_wait.wait(), timeout=1)
        await namespace["on_ready"](client)
        for worker in workers.values():
            worker.start.assert_called_once()
        assert client.guild_presence_synced
        client.refresh_primary_guild_assignments.assert_awaited_once()
        sync.assert_awaited_once()
        await client.command_sync.close()

    asyncio.run(scenario())
