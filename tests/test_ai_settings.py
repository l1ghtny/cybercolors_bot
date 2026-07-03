import pytest
from pydantic import ValidationError
from starlette.routing import Match

from api.api_main import app
from api.models.ai_settings import ServerAISettingsUpdateModel
from api.services.ai_settings_health import EMBED_LINKS, READ_MESSAGE_HISTORY, SEND_MESSAGES, VIEW_CHANNEL, build_ai_settings_health
from api.services.ai_settings import can_invoke_answer_flow, should_moderate_message_channel
from api.services.ai_settings import to_server_ai_settings_read_model, update_server_ai_settings
from src.db.models import ServerAISettings, ServerModerationSettings


def test_ai_settings_update_normalizes_ids_and_deduplicates():
    body = ServerAISettingsUpdateModel(
        answer_allowed_channel_ids=["123", " 456 ", "123"],
        answer_allowed_role_ids=["777", "777", "888"],
        moderation_included_channel_ids=["999", " 111 "],
    )

    assert body.answer_allowed_channel_ids == ["123", "456"]
    assert body.answer_allowed_role_ids == ["777", "888"]
    assert body.moderation_included_channel_ids == ["999", "111"]


def test_ai_settings_update_rejects_invalid_ids():
    with pytest.raises(ValidationError):
        ServerAISettingsUpdateModel(answer_allowed_role_ids=["123", "not-a-role"])


def test_ai_settings_update_rejects_selected_mode_with_empty_ids():
    with pytest.raises(ValidationError):
        ServerAISettingsUpdateModel(answer_channel_mode="selected", answer_allowed_channel_ids=[])

    with pytest.raises(ValidationError):
        ServerAISettingsUpdateModel(moderation_channel_mode="selected", moderation_included_channel_ids=[])


def test_ai_settings_route_is_registered_under_server_settings():
    _assert_route("/servers/123/ai-settings", "GET", "/servers/{server_id}/ai-settings")
    _assert_route("/servers/123/ai-settings/health", "GET", "/servers/{server_id}/ai-settings/health")


def _assert_route(path: str, method: str, expected_path: str):
    scope = {"type": "http", "method": method, "path": path}

    for route in app.routes:
        match, child_scope = route.matches(scope)
        if match == Match.FULL:
            assert route.path == expected_path
            assert child_scope["path_params"] == {"server_id": "123"}
            return

    raise AssertionError(f"Route did not match: {method} {path}")


def test_ai_settings_read_model_defaults_to_read_only_permission():
    settings = ServerAISettings(server_id=123)

    payload = to_server_ai_settings_read_model(settings)

    assert payload.permissions.can_edit is False
    assert payload.moderation_review_channel_id is None
    assert payload.moderation_kill_switch_enabled is False
    assert payload.moderation_daily_token_limit is None
    assert payload.moderation_provider_timeout_seconds == 20


def test_ai_settings_read_model_includes_review_channel():
    settings = ServerAISettings(server_id=123, moderation_review_channel_id=987)

    payload = to_server_ai_settings_read_model(settings)

    assert payload.moderation_review_channel_id == "987"


def test_ai_settings_update_accepts_runtime_limits():
    body = ServerAISettingsUpdateModel(
        moderation_kill_switch_enabled=True,
        moderation_daily_token_limit=5000,
        moderation_provider_timeout_seconds=12,
    )

    assert body.moderation_kill_switch_enabled is True
    assert body.moderation_daily_token_limit == 5000
    assert body.moderation_provider_timeout_seconds == 12


def test_ai_settings_update_accepts_blank_review_channel_as_clear():
    body = ServerAISettingsUpdateModel(moderation_review_channel_id="  ")

    assert body.moderation_review_channel_id == ""


def test_update_ai_settings_validates_and_stores_review_channel(monkeypatch):
    import asyncio

    settings = ServerAISettings(server_id=123)

    class FakeSession:
        async def get(self, model, key):
            return None

        def add(self, item):
            return None

        async def flush(self):
            return None

        async def refresh(self, item):
            return None

    async def fake_get_or_create(_session, server_id, server_name=None):
        assert server_id == 123
        return settings

    async def fake_fetch_channel(server_id, channel_id):
        assert server_id == 123
        assert channel_id == 456
        return {"id": "456", "type": 0, "name": "ai-review"}

    import api.services.ai_settings as ai_settings_service

    monkeypatch.setattr(ai_settings_service, "get_or_create_server_ai_settings", fake_get_or_create)
    monkeypatch.setattr(ai_settings_service, "fetch_channel", fake_fetch_channel)

    asyncio.run(
        update_server_ai_settings(
            FakeSession(),
            123,
            ServerAISettingsUpdateModel(moderation_review_channel_id="456"),
        )
    )

    assert settings.moderation_review_channel_id == 456

    asyncio.run(
        update_server_ai_settings(
            FakeSession(),
            123,
            ServerAISettingsUpdateModel(moderation_review_channel_id=""),
        )
    )

    assert settings.moderation_review_channel_id is None


def test_can_invoke_answer_flow_checks_channel_and_roles():
    settings = ServerAISettings(
        server_id=123,
        answer_channel_mode="selected",
        answer_allowed_channel_ids=["10"],
        answer_allowed_role_ids=["99"],
    )

    assert can_invoke_answer_flow(settings, channel_id=10, role_ids=[99]) is True
    assert can_invoke_answer_flow(settings, channel_id=11, role_ids=[99]) is False
    assert can_invoke_answer_flow(settings, channel_id=10, role_ids=[1]) is False

    settings.answer_channel_mode = "all"
    settings.answer_allowed_role_ids = []
    assert can_invoke_answer_flow(settings, channel_id=11, role_ids=[]) is True

    settings.answer_channel_mode = "none"
    assert can_invoke_answer_flow(settings, channel_id=10, role_ids=[99]) is False


def test_chat_response_channel_gate_uses_ai_settings(monkeypatch):
    import asyncio
    import src.modules.chat_bot.message_processing as message_processing

    settings = ServerAISettings(
        server_id=123,
        answer_channel_mode="selected",
        answer_allowed_channel_ids=["10"],
        answer_allowed_role_ids=["99"],
    )

    class FakeSession:
        async def get(self, model, key):
            assert model is ServerAISettings
            assert key == 123
            return settings

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeRole:
        id = 99

    class FakeGuild:
        id = 123

    class FakeChannel:
        id = 10

    class FakeAuthor:
        roles = [FakeRole()]

    class FakeMessage:
        guild = FakeGuild()
        channel = FakeChannel()
        author = FakeAuthor()

    monkeypatch.setattr(message_processing, "get_async_session", lambda: FakeSessionContext())

    allowed, channel = asyncio.run(message_processing.check_for_channel(FakeMessage(), client=None))

    assert allowed is True
    assert channel is FakeMessage.channel

    FakeMessage.channel.id = 11
    blocked, _channel = asyncio.run(message_processing.check_for_channel(FakeMessage(), client=None))
    assert blocked is False


def test_should_moderate_message_channel_checks_enabled_and_channel_mode():
    settings = ServerAISettings(
        server_id=123,
        moderation_enabled=True,
        moderation_channel_mode="selected",
        moderation_included_channel_ids=["10"],
    )

    assert should_moderate_message_channel(settings, channel_id=10) is True
    assert should_moderate_message_channel(settings, channel_id=11) is False

    settings.moderation_channel_mode = "all"
    assert should_moderate_message_channel(settings, channel_id=11) is True

    settings.moderation_review_channel_id = 11
    assert should_moderate_message_channel(settings, channel_id=11) is False

    settings.moderation_channel_mode = "selected"
    settings.moderation_included_channel_ids = ["11"]
    assert should_moderate_message_channel(settings, channel_id=11) is False

    settings.moderation_review_channel_id = None
    settings.moderation_channel_mode = "none"
    assert should_moderate_message_channel(settings, channel_id=10) is False

    settings.moderation_enabled = False
    settings.moderation_channel_mode = "all"
    assert should_moderate_message_channel(settings, channel_id=10) is False


def test_ai_settings_health_reports_channel_and_mod_log_permissions(monkeypatch):
    server_id = 123
    bot_id = 456
    readable_channel_id = 10
    blocked_channel_id = 11
    mod_log_channel_id = 12
    base_permissions = VIEW_CHANNEL | READ_MESSAGE_HISTORY
    settings = ServerAISettings(
        server_id=server_id,
        moderation_enabled=True,
        moderation_channel_mode="selected",
        moderation_included_channel_ids=[str(readable_channel_id), str(blocked_channel_id)],
        moderation_review_channel_id=mod_log_channel_id,
    )

    class FakeSession:
        async def get(self, model, key):
            if model is ServerModerationSettings:
                return ServerModerationSettings(server_id=server_id, mod_log_channel_id=mod_log_channel_id)
            return None

    async def fake_get_settings(_session, requested_server_id):
        assert requested_server_id == server_id
        return settings

    async def fake_channels(requested_server_id):
        assert requested_server_id == server_id
        return [
            {"id": str(readable_channel_id), "name": "readable", "type": 0, "permission_overwrites": []},
            {
                "id": str(blocked_channel_id),
                "name": "blocked",
                "type": 0,
                "permission_overwrites": [
                    {"id": str(server_id), "type": 0, "allow": "0", "deny": str(READ_MESSAGE_HISTORY)}
                ],
            },
            {"id": str(mod_log_channel_id), "name": "mod-log", "type": 0, "permission_overwrites": []},
        ]

    async def fake_roles(requested_server_id):
        assert requested_server_id == server_id
        return [{"id": str(server_id), "name": "@everyone", "permissions": str(base_permissions)}]

    async def fake_bot_user():
        return {"id": str(bot_id)}

    async def fake_member(server_id, user_id):
        assert user_id == bot_id
        return {"roles": []}

    import api.services.ai_settings_health as health_service

    monkeypatch.setattr(health_service, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(health_service, "fetch_guild_channels", fake_channels)
    monkeypatch.setattr(health_service, "fetch_guild_roles", fake_roles)
    monkeypatch.setattr(health_service, "fetch_current_bot_user", fake_bot_user)
    monkeypatch.setattr(health_service, "fetch_guild_member", fake_member)

    import asyncio

    payload = asyncio.run(build_ai_settings_health(FakeSession(), server_id))

    assert payload.ok is False
    assert payload.moderation_channels[0].ok is True
    assert payload.moderation_channels[1].ok is False
    assert payload.moderation_channels[1].can_read_message_history is False
    assert payload.mod_log_channel.ok is False
    assert payload.mod_log_channel.can_send_messages is False
    assert payload.mod_log_channel.can_embed_links is False
    assert payload.ai_review_channel.channel_id == str(mod_log_channel_id)
    assert payload.ai_review_channel.ok is False
    assert payload.ai_review_channel.purpose == "ai_review"
    assert payload.warnings


def test_ai_settings_health_reports_writable_mod_log(monkeypatch):
    server_id = 123
    bot_id = 456
    mod_log_channel_id = 12
    permissions = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES
    settings = ServerAISettings(server_id=server_id, moderation_enabled=False)

    class FakeSession:
        async def get(self, model, key):
            if model is ServerModerationSettings:
                return ServerModerationSettings(server_id=server_id, mod_log_channel_id=mod_log_channel_id)
            return None

    async def fake_get_settings(_session, _server_id):
        return settings

    async def fake_channels(_server_id):
        return [{"id": str(mod_log_channel_id), "name": "mod-log", "type": 0, "permission_overwrites": []}]

    async def fake_roles(_server_id):
        return [{"id": str(server_id), "name": "@everyone", "permissions": str(permissions | EMBED_LINKS)}]

    async def fake_bot_user():
        return {"id": str(bot_id)}

    async def fake_member(server_id, user_id):
        return {"roles": []}

    import asyncio
    import api.services.ai_settings_health as health_service

    monkeypatch.setattr(health_service, "get_or_create_server_ai_settings", fake_get_settings)
    monkeypatch.setattr(health_service, "fetch_guild_channels", fake_channels)
    monkeypatch.setattr(health_service, "fetch_guild_roles", fake_roles)
    monkeypatch.setattr(health_service, "fetch_current_bot_user", fake_bot_user)
    monkeypatch.setattr(health_service, "fetch_guild_member", fake_member)

    payload = asyncio.run(build_ai_settings_health(FakeSession(), server_id))

    assert payload.mod_log_channel.ok is True
    assert payload.ai_review_channel.ok is True
    assert payload.warnings == []
