import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from discord import app_commands

from src.commands.app_command_errors import handle_app_command_error


class FakeResponse:
    def __init__(self, *, done: bool):
        self.done = done
        self.messages: list[tuple[str, bool]] = []

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, content: str, *, ephemeral: bool) -> None:
        self.messages.append((content, ephemeral))


class FakeFollowup:
    def __init__(self):
        self.messages: list[tuple[str, bool]] = []

    async def send(self, content: str, *, ephemeral: bool) -> None:
        self.messages.append((content, ephemeral))


class FakeInteraction:
    def __init__(self, *, response_done: bool):
        self.id = 123456789
        self.guild_id = 478278763239702538
        self.user = SimpleNamespace(id=987654321)
        self.command = SimpleNamespace(qualified_name="mod actions list")
        self.response = FakeResponse(done=response_done)
        self.followup = FakeFollowup()


def test_missing_permissions_responds_before_command_callback() -> None:
    interaction = FakeInteraction(response_done=False)
    logger = Mock()

    asyncio.run(
        handle_app_command_error(
            interaction,
            app_commands.MissingPermissions(["moderate_members"]),
            logger=logger,
        )
    )

    assert interaction.response.messages == [
        (
            "You need the following Discord permission(s) to use this command: "
            "`moderate members`.",
            True,
        )
    ]
    assert interaction.followup.messages == []
    logger.warning.assert_called_once()


def test_unexpected_error_uses_followup_after_defer() -> None:
    interaction = FakeInteraction(response_done=True)
    logger = Mock()
    error = app_commands.CommandInvokeError(
        SimpleNamespace(name="list", qualified_name="mod actions list"),
        RuntimeError("database unavailable"),
    )

    asyncio.run(handle_app_command_error(interaction, error, logger=logger))

    assert interaction.response.messages == []
    assert interaction.followup.messages == [
        ("This command failed unexpectedly. The error has been logged.", True)
    ]
    logger.error.assert_called_once()
