import asyncio
from uuid import uuid4

import discord

from src.commands.moderation.actions import (
    ActionLogRevertButton,
    ActionRevertConfirmationView,
    register_moderation_action_components,
)
from src.modules.localization.service import tr


def test_action_log_revert_button_is_persistent_and_registered():
    action_id = str(uuid4())
    button = ActionLogRevertButton(action_id=action_id)
    registered: list[type] = []

    class FakeClient:
        def add_dynamic_items(self, *items):
            registered.extend(items)

    register_moderation_action_components(FakeClient())

    assert button.item.custom_id == f"mod-action:revert:{action_id}"
    assert button.item.style is discord.ButtonStyle.danger
    assert registered == [ActionLogRevertButton]


def test_action_revert_confirmation_has_explicit_confirm_and_cancel_steps():
    async def scenario():
        view = ActionRevertConfirmationView(
            action_id=str(uuid4()),
            locale="ru",
            requesting_user_id=123,
        )
        assert view.timeout == 60
        assert [item.label for item in view.children] == [
            tr("ru", "action.revert_confirm_button"),
            tr("ru", "action.revert_cancel_button"),
        ]
        assert [item.style for item in view.children] == [
            discord.ButtonStyle.danger,
            discord.ButtonStyle.secondary,
        ]

    asyncio.run(scenario())
