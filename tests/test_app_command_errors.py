import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from discord import AppCommandOptionType, app_commands
from discord.app_commands.transformers import MemberTransformer

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


def test_missing_permissions_responds_before_command_callback(monkeypatch) -> None:
    interaction = FakeInteraction(response_done=False)
    logger = Mock()
    monkeypatch.setattr("src.commands.app_command_errors.get_server_locale", AsyncMock(return_value="en"))

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


def test_unexpected_error_uses_followup_after_defer_and_guild_locale(monkeypatch) -> None:
    interaction = FakeInteraction(response_done=True)
    logger = Mock()
    locale_resolver = AsyncMock(return_value="ru")
    monkeypatch.setattr("src.commands.app_command_errors.get_server_locale", locale_resolver)
    error = app_commands.CommandInvokeError(
        SimpleNamespace(name="list", qualified_name="mod actions list"),
        RuntimeError("database unavailable"),
    )

    asyncio.run(handle_app_command_error(interaction, error, logger=logger))

    assert interaction.response.messages == []
    assert interaction.followup.messages == [
        ("Не удалось выполнить команду из-за внутренней ошибки. Ошибка записана в журнал.", True)
    ]
    locale_resolver.assert_awaited_once_with(interaction.guild_id)
    logger.error.assert_called_once()


def test_transform_error_uses_localized_actionable_message(monkeypatch) -> None:
    interaction = FakeInteraction(response_done=False)
    logger = Mock()
    monkeypatch.setattr("src.commands.app_command_errors.get_server_locale", AsyncMock(return_value="ru"))
    error = app_commands.TransformerError(
        "external-user",
        AppCommandOptionType.user,
        MemberTransformer(),
    )

    asyncio.run(handle_app_command_error(interaction, error, logger=logger))

    assert interaction.response.messages == [
        (
            "Не удалось распознать один из параметров команды. "
            "Выберите значение из актуальных подсказок и повторите попытку.",
            True,
        )
    ]
