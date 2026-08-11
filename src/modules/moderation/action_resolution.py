from datetime import datetime, timezone

from src.db.models import ActionType


ACTION_RESOLUTION_EXPIRED = "expired"
ACTION_RESOLUTION_EXPIRED_LEGACY = "expired_legacy"
ACTION_RESOLUTION_REVERTED = "reverted"
ACTION_RESOLUTION_SUPERSEDED = "superseded"


def infer_inactive_action_resolution(
    action_type: ActionType | str,
    is_active: bool,
    expires_at: datetime | None,
    *,
    now: datetime | None = None,
) -> str | None:
    if is_active:
        return None
    normalized = action_type.value if hasattr(action_type, "value") else str(action_type)
    if normalized not in {ActionType.WARN.value, ActionType.MUTE.value, ActionType.BAN.value}:
        return None
    if normalized in {ActionType.MUTE.value, ActionType.BAN.value} and expires_at is not None:
        normalized_expires_at = (
            expires_at.replace(tzinfo=timezone.utc)
            if expires_at.tzinfo is None
            else expires_at.astimezone(timezone.utc)
        )
        normalized_now = now or datetime.now(timezone.utc)
        if normalized_now.tzinfo is None:
            normalized_now = normalized_now.replace(tzinfo=timezone.utc)
        if normalized_expires_at <= normalized_now:
            return ACTION_RESOLUTION_EXPIRED_LEGACY
    return ACTION_RESOLUTION_REVERTED


def moderation_action_is_reverted(
    action_type: ActionType | str,
    is_active: bool,
    resolution_type: str | None = None,
) -> bool:
    if is_active:
        return False
    if resolution_type is not None:
        return resolution_type == ACTION_RESOLUTION_REVERTED
    normalized = action_type.value if hasattr(action_type, "value") else str(action_type)
    return normalized in {ActionType.WARN.value, ActionType.MUTE.value, ActionType.BAN.value}
