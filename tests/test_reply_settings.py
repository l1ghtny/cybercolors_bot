import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.models.bot_replies import ReplySettingsUpdateModel
from api.services.replies_service import (
    to_reply_settings_model,
    update_reply_settings,
)
from src.db.models import ServerReplySettings
from src.modules.on_message_processing.replies import automatic_reply_allowed


def _message(
    *,
    channel_id: int = 10,
    parent_id: int | None = None,
    user_id: int = 20,
    role_ids: tuple[int, ...] = (30,),
):
    channel = SimpleNamespace(id=channel_id, parent_id=parent_id)
    author = SimpleNamespace(
        id=user_id,
        roles=[SimpleNamespace(id=role_id) for role_id in role_ids],
    )
    return SimpleNamespace(channel=channel, author=author)


def test_automatic_reply_settings_allow_by_default():
    assert automatic_reply_allowed(_message(), None) is True
    assert automatic_reply_allowed(_message(), ServerReplySettings(server_id=1)) is True


def test_automatic_reply_settings_apply_channel_allow_and_deny_lists():
    settings = ServerReplySettings(
        server_id=1,
        included_channel_ids=["10", "11"],
        excluded_channel_ids=["12"],
    )

    assert automatic_reply_allowed(_message(channel_id=10), settings) is True
    assert automatic_reply_allowed(_message(channel_id=12), settings) is False
    assert automatic_reply_allowed(_message(channel_id=13), settings) is False


def test_automatic_reply_settings_apply_parent_channel_rules_to_threads():
    settings = ServerReplySettings(
        server_id=1,
        included_channel_ids=["10"],
        excluded_channel_ids=[],
    )
    assert automatic_reply_allowed(_message(channel_id=99, parent_id=10), settings) is True

    settings.excluded_channel_ids = ["10"]
    assert automatic_reply_allowed(_message(channel_id=99, parent_id=10), settings) is False


def test_automatic_reply_settings_exclude_users_and_roles():
    settings = ServerReplySettings(
        server_id=1,
        excluded_user_ids=["20"],
        excluded_role_ids=["30"],
    )

    assert automatic_reply_allowed(_message(user_id=20, role_ids=()), settings) is False
    assert automatic_reply_allowed(_message(user_id=21, role_ids=(30,)), settings) is False
    assert automatic_reply_allowed(_message(user_id=21, role_ids=(31,)), settings) is True


def test_reply_settings_payload_normalizes_ids_and_rejects_channel_overlap():
    body = ReplySettingsUpdateModel(
        included_channel_ids=[" 10 ", "10"],
        excluded_role_ids=["30", "30"],
    )
    assert body.included_channel_ids == ["10"]
    assert body.excluded_role_ids == ["30"]

    with pytest.raises(ValidationError):
        ReplySettingsUpdateModel(
            included_channel_ids=["10"],
            excluded_channel_ids=["10"],
        )


def test_update_reply_settings_persists_all_filters(monkeypatch):
    settings = ServerReplySettings(server_id=1)

    class FakeSession:
        def __init__(self):
            self.added = []
            self.flushed = False
            self.refreshed = False

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            self.flushed = True

        async def refresh(self, item):
            assert item is settings
            self.refreshed = True

    async def fake_get_or_create(_session, server_id):
        assert server_id == 1
        return settings

    monkeypatch.setattr(
        "api.services.replies_service.get_or_create_reply_settings",
        fake_get_or_create,
    )
    session = FakeSession()
    body = ReplySettingsUpdateModel(
        included_channel_ids=["10"],
        excluded_channel_ids=["11"],
        excluded_role_ids=["30"],
        excluded_user_ids=["20"],
    )

    result = asyncio.run(update_reply_settings(session, 1, body))
    payload = to_reply_settings_model(result)

    assert payload.included_channel_ids == ["10"]
    assert payload.excluded_channel_ids == ["11"]
    assert payload.excluded_role_ids == ["30"]
    assert payload.excluded_user_ids == ["20"]
    assert session.added == [settings]
    assert session.flushed is True
    assert session.refreshed is True
