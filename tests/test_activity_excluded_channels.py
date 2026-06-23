import pytest
from pydantic import ValidationError

from api.models.moderation_settings import ServerModerationSettingsUpdateModel
from api.routers.activity import _resolve_effective_activity_excluded_channel_ids


def test_moderation_settings_update_normalizes_activity_excluded_channel_ids():
    body = ServerModerationSettingsUpdateModel(
        activity_excluded_channel_ids=["123", " 456 ", "123"],
    )

    assert body.activity_excluded_channel_ids == ["123", "456"]


def test_moderation_settings_update_allows_null_activity_excluded_channel_ids():
    body = ServerModerationSettingsUpdateModel(activity_excluded_channel_ids=None)

    assert body.activity_excluded_channel_ids is None


def test_moderation_settings_update_rejects_invalid_activity_excluded_channel_ids():
    with pytest.raises(ValidationError):
        ServerModerationSettingsUpdateModel(activity_excluded_channel_ids=["123", "not-a-channel"])


def test_leaderboard_server_excludes_merge_with_query_excludes_by_default():
    effective_excludes, applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids={111},
        server_excluded_channel_ids={222, 333},
        include_channel_ids=None,
        ignore_server_excludes=False,
    )

    assert effective_excludes == {111, 222, 333}
    assert applied is True


def test_leaderboard_include_channels_bypass_server_excludes():
    effective_excludes, applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids={111},
        server_excluded_channel_ids={222, 333},
        include_channel_ids={222},
        ignore_server_excludes=False,
    )

    assert effective_excludes == {111}
    assert applied is False


def test_leaderboard_ignore_server_excludes_bypasses_server_excludes():
    effective_excludes, applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids=None,
        server_excluded_channel_ids={222, 333},
        include_channel_ids=None,
        ignore_server_excludes=True,
    )

    assert effective_excludes is None
    assert applied is False