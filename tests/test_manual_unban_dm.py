import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import api.services.moderation_actions_service as action_service
from src.db.models import Server, ServerLocalizationSettings


class FakeSession:
    async def get(self, model, key):
        if model is Server:
            return Server(server_id=key, server_name="CyberColors")
        if model is ServerLocalizationSettings:
            return ServerLocalizationSettings(server_id=key, locale_code="ru")
        return None


def test_manual_unban_sends_localized_dm(monkeypatch):
    sent: list[tuple[int, str]] = []

    async def fake_create_direct_message(user_id: int, content: str):
        sent.append((user_id, content))
        return {"id": "1"}

    monkeypatch.setattr(action_service, "create_direct_message", fake_create_direct_message)
    delivered = asyncio.run(
        action_service.send_manual_unban_dm(
            session=FakeSession(),
            server_id=123,
            target_user_id=456,
            reason="Решение пересмотрено",
        )
    )

    assert delivered is True
    assert sent == [
        (
            456,
            "Вы разбанены на сервере **CyberColors**.\n\n**Причина:**\n> Решение пересмотрено",
        )
    ]


def test_manual_unban_dm_failure_is_best_effort(monkeypatch):
    async def fake_create_direct_message(user_id: int, content: str):
        raise RuntimeError("Cannot send messages to this user due to having no mutual guilds")

    monkeypatch.setattr(action_service, "create_direct_message", fake_create_direct_message)

    delivered = asyncio.run(
        action_service.send_manual_unban_dm(
            session=FakeSession(),
            server_id=123,
            target_user_id=456,
            reason="Manual unban",
        )
    )

    assert delivered is False


def test_unban_receipt_reports_undelivered_dm(monkeypatch):
    import src.commands.moderation.actions as actions_module

    session = SimpleNamespace(commit=AsyncMock())
    receipt_kwargs: dict = {}

    @asynccontextmanager
    async def fake_session_context():
        yield session

    def fake_build_receipt(**kwargs):
        receipt_kwargs.update(kwargs)
        return "receipt"

    guild = SimpleNamespace(id=123, unban=AsyncMock())
    interaction = SimpleNamespace(
        guild=guild,
        user=SimpleNamespace(id=789),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    target = SimpleNamespace(id=456, mention="<@456>")

    monkeypatch.setattr(actions_module, "get_async_session", fake_session_context)
    monkeypatch.setattr(actions_module, "get_server_locale", AsyncMock(return_value="ru"))
    monkeypatch.setattr(actions_module, "ensure_bot_permission", AsyncMock(return_value=True))
    monkeypatch.setattr(actions_module, "deactivate_user_bans", AsyncMock(return_value=1))
    monkeypatch.setattr(actions_module, "send_manual_unban_dm", AsyncMock(return_value=False))
    monkeypatch.setattr(actions_module, "send_public_action_notice", AsyncMock())
    monkeypatch.setattr(actions_module, "build_moderator_action_receipt", fake_build_receipt)

    asyncio.run(actions_module.unban.callback(interaction, target))

    assert ("Личное сообщение", "Не доставлено") in receipt_kwargs["extra_lines"]
    interaction.followup.send.assert_awaited_once()
    receipt_call = interaction.followup.send.await_args
    assert receipt_call.args == ("receipt",)
    assert receipt_call.kwargs["ephemeral"] is True
    assert receipt_call.kwargs["allowed_mentions"].everyone is False
    session.commit.assert_awaited_once()
