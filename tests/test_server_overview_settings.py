import pytest
from pydantic import ValidationError

from api.models.server_overview_settings import ServerOverviewSettingsUpdateModel


def test_overview_role_ids_are_trimmed_and_deduplicated():
    payload = ServerOverviewSettingsUpdateModel(
        role_ids=[" 123456789012345678 ", "123456789012345678", "987654321098765432"],
    )

    assert payload.role_ids == ["123456789012345678", "987654321098765432"]


@pytest.mark.parametrize(
    "role_ids",
    [
        ["not-a-role"],
        [str(index) for index in range(1, 8)],
    ],
)
def test_overview_role_ids_reject_invalid_values(role_ids):
    with pytest.raises(ValidationError):
        ServerOverviewSettingsUpdateModel(role_ids=role_ids)
