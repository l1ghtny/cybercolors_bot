import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import aiohttp
import discord
from discord import app_commands

logger = logging.getLogger("bot")


class BackgroundCommandSync:
    """Run one registration task without blocking the bot's ready handler."""

    def __init__(
        self,
        sync: Callable[[], Awaitable[None]],
        wait_until_ready: Callable[[], Awaitable[None]],
    ) -> None:
        self._sync = sync
        self._wait_until_ready = wait_until_ready
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        # READY may fire repeatedly. A completed task also stays completed:
        # registration succeeds once, or needs an operator fix after a hard error.
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="discord-command-sync")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        delay = 5
        while True:
            await self._wait_until_ready()
            try:
                await self._sync()
            except discord.HTTPException as exc:
                if exc.status != 429 and not 500 <= exc.status < 600:
                    logger.exception("Discord command sync failed; registration needs operator attention.")
                    return
                logger.warning(
                    "Discord command sync returned HTTP %s; retrying in %ss.", exc.status, delay
                )
            except (OSError, asyncio.TimeoutError, aiohttp.ClientError):
                logger.warning("Discord command sync connection failed; retrying in %ss.", delay)
            except Exception:
                logger.exception("Discord command sync failed; registration needs operator attention.")
                return
            else:
                logger.info("Discord command sync completed.")
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)


@dataclass(frozen=True)
class CommandSyncResult:
    global_count: int
    guild_counts: dict[int, int] = field(default_factory=dict)


async def sync_guild_application_commands(
    tree: app_commands.CommandTree,
    *,
    guild_id: int,
    commands: Sequence[app_commands.Command | app_commands.Group | app_commands.ContextMenu],
) -> int:
    """Replace one guild's command registry with the supplied commands."""
    guild = discord.Object(id=guild_id)
    tree.clear_commands(guild=guild)
    for command in commands:
        tree.add_command(command, guild=guild)
    return len(await tree.sync(guild=guild))


async def sync_application_commands(
    tree: app_commands.CommandTree,
    *,
    guild_ids: Sequence[int] = (),
    test_guild_id: str | None,
    standard_guild_commands: Sequence[
        app_commands.Command | app_commands.Group | app_commands.ContextMenu
    ] = (),
    test_guild_commands: Sequence[
        app_commands.Command | app_commands.Group | app_commands.ContextMenu
    ] = (),
) -> CommandSyncResult:
    """Sync globals and replace each guild registry with the supplied commands."""
    global_commands = await tree.sync()
    pilot_guild_id = int(test_guild_id) if test_guild_id else None
    target_guild_ids = {int(guild_id) for guild_id in guild_ids}
    if pilot_guild_id is not None:
        target_guild_ids.add(pilot_guild_id)

    guild_counts: dict[int, int] = {}
    for guild_id in sorted(target_guild_ids):
        commands = (
            test_guild_commands
            if guild_id == pilot_guild_id
            else standard_guild_commands
        )
        guild_counts[guild_id] = await sync_guild_application_commands(
            tree,
            guild_id=guild_id,
            commands=commands,
        )

    return CommandSyncResult(
        global_count=len(global_commands),
        guild_counts=guild_counts,
    )
