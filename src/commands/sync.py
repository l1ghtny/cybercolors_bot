from collections.abc import Sequence
from dataclasses import dataclass

import discord
from discord import app_commands


@dataclass(frozen=True)
class CommandSyncResult:
    global_count: int
    guild_id: int | None = None
    guild_count: int = 0


async def sync_application_commands(
    tree: app_commands.CommandTree,
    *,
    test_guild_id: str | None,
    test_guild_commands: Sequence[
        app_commands.Command | app_commands.Group | app_commands.ContextMenu
    ] = (),
) -> CommandSyncResult:
    """Sync globals and replace the test guild registry with explicit overrides."""
    global_commands = await tree.sync()
    if not test_guild_id:
        return CommandSyncResult(global_count=len(global_commands))

    guild_id = int(test_guild_id)
    guild = discord.Object(id=guild_id)
    tree.clear_commands(guild=guild)
    for command in test_guild_commands:
        tree.add_command(command, guild=guild)
    guild_commands = await tree.sync(guild=guild)
    return CommandSyncResult(
        global_count=len(global_commands),
        guild_id=guild_id,
        guild_count=len(guild_commands),
    )
