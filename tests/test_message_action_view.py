import asyncio
from types import SimpleNamespace

import discord
from discord import app_commands

from src.commands.moderation.message_actions import (
    LinkMessageToActionView,
    StartActionFromMessageView,
)
from src.db.models import ActionType


class FakeResponse:
    def __init__(self) -> None:
        self.edited_views = []
        self.deferred = 0

    async def edit_message(self, *, view) -> None:
        self.edited_views.append(view)

    async def defer(self) -> None:
        self.deferred += 1


def test_warning_selection_disables_and_clears_duration() -> None:
    async def run() -> None:
        view = StartActionFromMessageView(
            source_message=SimpleNamespace(),
            rules=[SimpleNamespace(id=1, code="R1", title="Test rule")],
            locale="en",
            requesting_user_id=123,
        )
        response = FakeResponse()
        view.duration = "1d"
        view.duration_select.options[3].default = True

        await view._select_action_type(
            SimpleNamespace(
                data={"values": [ActionType.WARN.value]},
                response=response,
            )
        )

        assert view.duration_select.disabled is True
        assert view.duration == "default"
        assert not any(option.default for option in view.duration_select.options)
        assert view.duration_select.placeholder == "Duration is not used for warnings"

        await view._select_duration(
            SimpleNamespace(data={"values": ["30d"]}, response=response)
        )

        assert view.duration == "default"
        assert response.deferred == 1

        await view._select_action_type(
            SimpleNamespace(
                data={"values": [ActionType.MUTE.value]},
                response=response,
            )
        )

        assert view.duration_select.disabled is False
        assert view.duration_select.placeholder == "Duration for mute or ban"
        assert response.edited_views == [view, view]

    asyncio.run(run())


def test_link_message_view_lists_recent_actions_and_search_button() -> None:
    async def run() -> None:
        view = LinkMessageToActionView(
            source_message=SimpleNamespace(),
            locale="en",
            requesting_user_id=123,
            choices=[
                app_commands.Choice(
                    name="WARN · Example User · #42 · 2026-07-21 12:30 · Rule 1",
                    value="42",
                )
            ],
        )

        selects = [item for item in view.children if isinstance(item, discord.ui.Select)]
        buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]

        assert len(selects) == 1
        assert selects[0].placeholder == "Choose a recent action"
        assert [(option.label, option.value) for option in selects[0].options] == [
            ("WARN · Example User · #42 · 2026-07-21 12:30 · Rule 1", "42")
        ]
        assert [button.label for button in buttons] == ["Search actions"]

    asyncio.run(run())
