import asyncio

import discord
from discord import app_commands

from src.commands.moderation.message_actions import (
    link_message_to_action_ctx,
    start_action_from_message_ctx,
)
from src.commands.moderation.bot_messages import (
    ReplyAsBotModal,
    StaticCommandTranslator,
    bot_display_name,
    reply_as_bot_ctx,
    reply_as_cybercolors_ctx,
)
from src.commands.sync import sync_application_commands


class FakeCommandTree:
    def __init__(self):
        self.sync_guild_ids: list[int | None] = []
        self.cleared_guild_ids: list[int] = []
        self.added_guild_commands: list[tuple[int, object]] = []

    async def sync(self, *, guild=None):
        guild_id = guild.id if guild is not None else None
        self.sync_guild_ids.append(guild_id)
        if guild is None:
            return [object(), object()]
        return [
            command
            for command_guild_id, command in self.added_guild_commands
            if command_guild_id == guild_id
        ]

    def clear_commands(self, *, guild):
        self.cleared_guild_ids.append(guild.id)

    def add_command(self, command, *, guild):
        self.added_guild_commands.append((guild.id, command))


def test_command_sync_replaces_test_guild_registry_with_single_branded_override():
    tree = FakeCommandTree()

    result = asyncio.run(
        sync_application_commands(
            tree,
            test_guild_id="478278763239702538",
            test_guild_commands=(reply_as_cybercolors_ctx,),
        )
    )

    assert tree.sync_guild_ids == [None, 478278763239702538]
    assert tree.cleared_guild_ids == [478278763239702538]
    assert tree.added_guild_commands == [
        (478278763239702538, reply_as_cybercolors_ctx)
    ]
    assert result.global_count == 2
    assert result.guild_id == 478278763239702538
    assert result.guild_count == 1


def test_command_sync_without_test_guild_only_updates_global_registry():
    tree = FakeCommandTree()

    result = asyncio.run(sync_application_commands(tree, test_guild_id=None))

    assert tree.sync_guild_ids == [None]
    assert tree.cleared_guild_ids == []
    assert tree.added_guild_commands == []
    assert result.global_count == 2
    assert result.guild_id is None


def test_message_context_commands_remain_moderator_only_by_default():
    expected = discord.Permissions(moderate_members=True)

    assert link_message_to_action_ctx.default_permissions == expected
    assert start_action_from_message_ctx.default_permissions == expected
    assert reply_as_bot_ctx.default_permissions == expected
    assert reply_as_cybercolors_ctx.default_permissions == expected
    assert link_message_to_action_ctx.guild_only is True
    assert start_action_from_message_ctx.guild_only is True
    assert reply_as_bot_ctx.guild_only is True
    assert reply_as_cybercolors_ctx.guild_only is True


def test_branded_context_command_overrides_global_identity_without_duplicate():
    assert reply_as_cybercolors_ctx.name == reply_as_bot_ctx.name
    assert reply_as_cybercolors_ctx.type == reply_as_bot_ctx.type


def test_cybercolors_context_command_payload_overrides_display_name_by_locale():
    translator = StaticCommandTranslator()

    async def translated_payload():
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        return await reply_as_cybercolors_ctx.get_translated_payload(tree, translator)

    payload = asyncio.run(translated_payload())

    assert payload["name"] == "Reply as Modral"
    assert payload["name_localizations"]["en-US"] == "Reply as CyberColors"
    assert payload["name_localizations"]["en-GB"] == "Reply as CyberColors"
    assert payload["name_localizations"]["ru"] == "Ответить от имени CyberColors"


def test_bot_display_name_uses_test_guild_as_cybercolors(monkeypatch):
    monkeypatch.setenv("TEST_GUILD_ID", "478278763239702538")

    assert bot_display_name(478278763239702538) == "CyberColors"
    assert bot_display_name(123456789012345678) == "Modral"


def test_reply_modal_has_native_notification_checkbox_defaulting_off():
    english = ReplyAsBotModal(
        server_id=1,
        channel_id=2,
        message_id=3,
        requesting_user_id=4,
        locale="en",
        bot_name="CyberColors",
    )
    russian = ReplyAsBotModal(
        server_id=1,
        channel_id=2,
        message_id=3,
        requesting_user_id=4,
        locale="ru",
        bot_name="CyberColors",
    )

    assert english.notify_replied_user_input.default is False
    assert english.notify_replied_user_input.value is False
    english_checkbox = english.to_components()[1]
    russian_checkbox = russian.to_components()[1]
    assert english_checkbox == {
        "type": discord.ComponentType.label.value,
        "label": "Notify the replied-to author",
        "description": "Send Discord's reply notification to this user.",
        "component": {
            "type": discord.ComponentType.checkbox.value,
            "custom_id": "notify_replied_user",
            "default": False,
        },
    }
    assert russian_checkbox["label"] == "Уведомить автора сообщения"
