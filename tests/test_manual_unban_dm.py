import asyncio

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
    asyncio.run(
        action_service.send_manual_unban_dm(
            session=FakeSession(),
            server_id=123,
            target_user_id=456,
            reason="Решение пересмотрено",
        )
    )

    assert sent == [
        (
            456,
            "Вы разбанены на сервере **CyberColors**.\n\n**Причина:**\n> Решение пересмотрено",
        )
    ]
