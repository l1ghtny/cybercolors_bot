from datetime import datetime, timedelta, timezone

from api.models.moderation_actions import ModerationActionCreate
from src.db.models import ActionType


def _action_payload(expires_at: datetime) -> ModerationActionCreate:
    return ModerationActionCreate(
        action_type=ActionType.MUTE,
        reason="Rule violation",
        expires_at=expires_at,
        target_user_id=1,
        target_user_name="target",
        target_user_joined_at=datetime(2026, 7, 1, 12, 0),
        target_user_server_nickname=None,
        server_id=478278763239702538,
        server_name="CyberColors",
    )


def test_action_expiry_is_normalized_to_naive_utc_for_postgres() -> None:
    local_tz = timezone(timedelta(hours=3))
    action = _action_payload(datetime(2026, 7, 19, 17, 54, tzinfo=local_tz))

    assert action.expires_at == datetime(2026, 7, 19, 14, 54)
    assert action.expires_at.tzinfo is None


def test_naive_action_expiry_is_preserved() -> None:
    expires_at = datetime(2026, 7, 19, 14, 54)

    assert _action_payload(expires_at).expires_at == expires_at
