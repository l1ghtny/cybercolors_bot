from datetime import datetime

from api.models.moderation_actions import ModerationActionSummaryModel
from src.db.models import ActionType
from src.modules.moderation.bot_services import action_choices


def _action(
    *,
    action_id: str,
    username: str,
    reason: str,
) -> ModerationActionSummaryModel:
    return ModerationActionSummaryModel(
        id=action_id,
        action_number=42,
        action_type=ActionType.MUTE,
        server_id="478278763239702538",
        target_user_id="895261951293292585",
        target_user_username=username,
        moderator_user_id="264788612803985408",
        moderator_username="moderator",
        reason=reason,
        created_at=datetime(2026, 7, 19, 14, 44),
        is_active=True,
    )


def test_action_choices_show_readable_label_and_use_action_number_value() -> None:
    action_id = "019f7ad5-af78-77b2-a23e-23569a3f3cd7"
    choices = action_choices(
        [_action(action_id=action_id, username="Denis Bailyn", reason="Rule 9 violation")],
        "",
    )

    assert len(choices) == 1
    assert choices[0].value == "42"
    assert choices[0].name.startswith("MUTE · Denis Bailyn · #42 · 2026-07-19 14:44")
    assert len(choices[0].name) <= 100


def test_action_choices_filter_by_username_target_id_and_full_uuid() -> None:
    action_id = "019f7ad5-af78-77b2-a23e-23569a3f3cd7"
    action = _action(action_id=action_id, username="Denis Bailyn", reason="Rule 9 violation")

    assert action_choices([action], "denis")
    assert action_choices([action], "895261951293292585")
    assert action_choices([action], "a23e-23569a3f3cd7")
    assert action_choices([action], "not present") == []


def test_action_choices_truncate_long_labels_to_discord_limit() -> None:
    action = _action(
        action_id="019f7ad5-af78-77b2-a23e-23569a3f3cd7",
        username="Denis Bailyn",
        reason="very long reason " * 20,
    )

    choice = action_choices([action], "")[0]

    assert len(choice.name) == 100
    assert choice.name.endswith("...")
