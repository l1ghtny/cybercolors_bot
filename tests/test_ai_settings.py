import pytest
from pydantic import ValidationError
from starlette.routing import Match

from api.api_main import app
from api.models.ai_settings import ServerAISettingsUpdateModel
from api.services.ai_settings import can_invoke_answer_flow, should_moderate_message_channel
from src.db.models import ServerAISettings


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
    path = "/servers/123/ai-settings"
    scope = {"type": "http", "method": "GET", "path": path}

    for route in app.routes:
        match, child_scope = route.matches(scope)
        if match == Match.FULL:
            assert route.path == "/servers/{server_id}/ai-settings"
            assert child_scope["path_params"] == {"server_id": "123"}
            return

    raise AssertionError("AI settings route did not match")


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

    settings.moderation_channel_mode = "none"
    assert should_moderate_message_channel(settings, channel_id=10) is False

    settings.moderation_enabled = False
    settings.moderation_channel_mode = "all"
    assert should_moderate_message_channel(settings, channel_id=10) is False
