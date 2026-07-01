import asyncio
from uuid import uuid4

from api.services.moderation_settings import check_mod_log_setting, check_mute_role_setting
from src.db.models import Server, ServerLocalizationSettings, ServerModerationSettings
from src.modules.localization.service import tr


def _make_discord_id() -> int:
    return 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


class FakeSession:
    def __init__(self, settings: ServerModerationSettings, locale_code: str | None = None):
        self.settings = settings
        self.locale_code = locale_code

    async def get(self, model, key):
        if model is Server:
            return Server(server_id=key, server_name="moderation-settings-test", bot_active=True)
        if model is ServerModerationSettings:
            return self.settings
        if model is ServerLocalizationSettings and self.locale_code:
            return ServerLocalizationSettings(server_id=key, locale_code=self.locale_code)
        return None


async def _moderation_settings_test_scenario(monkeypatch) -> None:
    import api.services.moderation_settings as moderation_settings_service

    server_id = _make_discord_id()
    mute_role_id = _make_discord_id()
    mod_log_channel_id = _make_discord_id()
    sent_messages: list[dict] = []

    async def fake_fetch_guild_roles(server_id: int) -> list[dict]:
        return [{"id": str(mute_role_id), "name": "Muted", "managed": False}]

    async def fake_fetch_channel(server_id: int, channel_id: int) -> dict | None:
        if channel_id == mod_log_channel_id:
            return {"id": str(channel_id), "name": "mod-log", "type": 0}
        return None

    async def fake_create_channel_message(
        channel_id: int,
        content: str | None = None,
        embeds: list[dict] | None = None,
    ) -> dict:
        sent_messages.append({"channel_id": channel_id, "content": content, "embeds": embeds})
        return {"id": str(_make_discord_id())}

    monkeypatch.setattr(moderation_settings_service, "fetch_guild_roles", fake_fetch_guild_roles)
    monkeypatch.setattr(moderation_settings_service, "fetch_channel", fake_fetch_channel)
    monkeypatch.setattr(moderation_settings_service, "create_channel_message", fake_create_channel_message)

    session = FakeSession(
        ServerModerationSettings(
            server_id=server_id,
            mute_role_id=mute_role_id,
            mod_log_channel_id=mod_log_channel_id,
        )
    )

    mute_result = await check_mute_role_setting(session=session, server_id=server_id)
    mod_log_result = await check_mod_log_setting(session=session, server_id=server_id)

    assert mute_result.ok is True
    assert mute_result.error is None
    assert mod_log_result.ok is True
    assert mod_log_result.error is None
    assert sent_messages == [
        {
            "channel_id": mod_log_channel_id,
            "content": tr("en", "settings.mod_log_test_message"),
            "embeds": None,
        }
    ]

    sent_messages.clear()
    ru_session = FakeSession(
        ServerModerationSettings(
            server_id=server_id,
            mute_role_id=mute_role_id,
            mod_log_channel_id=mod_log_channel_id,
        ),
        locale_code="ru",
    )
    ru_result = await check_mod_log_setting(session=ru_session, server_id=server_id)

    assert ru_result.ok is True
    assert sent_messages == [
        {
            "channel_id": mod_log_channel_id,
            "content": tr("ru", "settings.mod_log_test_message"),
            "embeds": None,
        }
    ]


async def _moderation_settings_test_failures_scenario(monkeypatch) -> None:
    import api.services.moderation_settings as moderation_settings_service

    server_id = _make_discord_id()
    mute_role_id = _make_discord_id()
    mod_log_channel_id = _make_discord_id()

    async def fake_fetch_guild_roles(server_id: int) -> list[dict]:
        return [{"id": str(mute_role_id), "name": "Muted", "managed": True}]

    async def fake_fetch_channel(server_id: int, channel_id: int) -> dict | None:
        if channel_id == mod_log_channel_id:
            return {"id": str(channel_id), "name": "voice-chat", "type": 2}
        return None

    monkeypatch.setattr(moderation_settings_service, "fetch_guild_roles", fake_fetch_guild_roles)
    monkeypatch.setattr(moderation_settings_service, "fetch_channel", fake_fetch_channel)

    session = FakeSession(
        ServerModerationSettings(
            server_id=server_id,
            mute_role_id=mute_role_id,
            mod_log_channel_id=mod_log_channel_id,
        )
    )

    mute_result = await check_mute_role_setting(session=session, server_id=server_id)
    mod_log_result = await check_mod_log_setting(session=session, server_id=server_id)

    assert mute_result.ok is False
    assert "managed" in (mute_result.error or "")
    assert mod_log_result.ok is False
    assert "text or announcement channel" in (mod_log_result.error or "")


def test_moderation_settings_test_endpoints_success_contract(monkeypatch):
    asyncio.run(_moderation_settings_test_scenario(monkeypatch))


def test_moderation_settings_test_endpoints_failure_contract(monkeypatch):
    asyncio.run(_moderation_settings_test_failures_scenario(monkeypatch))
