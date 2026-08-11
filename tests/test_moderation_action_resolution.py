from datetime import datetime, timedelta, timezone

from src.db.models import ActionType
from src.modules.moderation.action_resolution import (
    ACTION_RESOLUTION_EXPIRED,
    ACTION_RESOLUTION_EXPIRED_LEGACY,
    ACTION_RESOLUTION_REVERTED,
    infer_inactive_action_resolution,
    moderation_action_is_reverted,
)


def test_inactive_timed_action_is_inferred_as_expired_after_its_deadline():
    now = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)

    assert infer_inactive_action_resolution(
        ActionType.MUTE,
        False,
        now - timedelta(minutes=1),
        now=now,
    ) == ACTION_RESOLUTION_EXPIRED_LEGACY


def test_early_or_indefinite_inactive_action_is_inferred_as_reverted():
    now = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)

    assert infer_inactive_action_resolution(
        ActionType.BAN,
        False,
        now + timedelta(minutes=1),
        now=now,
    ) == ACTION_RESOLUTION_REVERTED
    assert infer_inactive_action_resolution(
        ActionType.WARN,
        False,
        None,
        now=now,
    ) == ACTION_RESOLUTION_REVERTED


def test_persisted_resolution_controls_reverted_flag():
    assert moderation_action_is_reverted(
        ActionType.MUTE,
        False,
        ACTION_RESOLUTION_REVERTED,
    )
    assert not moderation_action_is_reverted(
        ActionType.MUTE,
        False,
        ACTION_RESOLUTION_EXPIRED,
    )
    assert not moderation_action_is_reverted(
        ActionType.MUTE,
        False,
        ACTION_RESOLUTION_EXPIRED_LEGACY,
    )


def test_active_and_non_reversible_actions_have_no_inactive_resolution():
    assert infer_inactive_action_resolution(ActionType.MUTE, True, None) is None
    assert infer_inactive_action_resolution(ActionType.KICK, False, None) is None
