import pytest
from pydantic import ValidationError

from api.models.moderation_settings import ServerModerationSettingsUpdateModel


def test_ban_presets_accept_three_months_and_normalize_values():
    body = ServerModerationSettingsUpdateModel(
        ban_duration_presets=[129_600, 43_200, 129_600],
    )

    assert body.ban_duration_presets == [43_200, 129_600]


def test_ban_default_and_presets_accept_up_to_one_year():
    body = ServerModerationSettingsUpdateModel(
        default_ban_minutes=525_600,
        ban_duration_presets=[43_200, 518_400, 525_600],
    )

    assert body.default_ban_minutes == 525_600
    assert body.ban_duration_presets == [43_200, 518_400, 525_600]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mute_duration_presets", [43_201]),
        ("ban_duration_presets", [525_601]),
        ("default_ban_minutes", 525_601),
    ],
)
def test_duration_settings_reject_values_over_the_action_limit(field, value):
    with pytest.raises(ValidationError):
        ServerModerationSettingsUpdateModel(**{field: value})
