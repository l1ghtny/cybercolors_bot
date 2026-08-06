from collections.abc import Sequence
from dataclasses import dataclass, field

import discord
from discord import app_commands


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
