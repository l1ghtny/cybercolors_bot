import asyncio

import discord

from src.commands.moderation.message_actions import (
    link_message_to_action_ctx,
    start_action_from_message_ctx,
)
from src.commands.sync import sync_application_commands


class FakeCommandTree:
    def __init__(self):
        self.sync_guild_ids: list[int | None] = []
        self.copied_guild_ids: list[int] = []

    async def sync(self, *, guild=None):
        guild_id = guild.id if guild is not None else None
        self.sync_guild_ids.append(guild_id)
        return [object(), object()] if guild is None else [object()]

    def copy_global_to(self, *, guild):
        self.copied_guild_ids.append(guild.id)


def test_command_sync_always_updates_global_registry_and_test_guild():
    tree = FakeCommandTree()

    result = asyncio.run(
        sync_application_commands(tree, test_guild_id="478278763239702538")
    )

    assert tree.sync_guild_ids == [None, 478278763239702538]
    assert tree.copied_guild_ids == [478278763239702538]
    assert result.global_count == 2
    assert result.guild_id == 478278763239702538
    assert result.guild_count == 1


def test_command_sync_without_test_guild_only_updates_global_registry():
    tree = FakeCommandTree()

    result = asyncio.run(sync_application_commands(tree, test_guild_id=None))

    assert tree.sync_guild_ids == [None]
    assert tree.copied_guild_ids == []
    assert result.global_count == 2
    assert result.guild_id is None


def test_message_context_commands_remain_moderator_only_by_default():
    expected = discord.Permissions(moderate_members=True)

    assert link_message_to_action_ctx.default_permissions == expected
    assert start_action_from_message_ctx.default_permissions == expected
    assert link_message_to_action_ctx.guild_only is True
    assert start_action_from_message_ctx.guild_only is True
