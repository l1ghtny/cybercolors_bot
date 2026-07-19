from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.models.monitoring import (
    MonitoredUserUpdateModel,
    ServerMonitoringSettingsUpdateModel,
)
from api.services.moderation_core import naive_utcnow
from api.services.monitoring_service import (
    monitoring_notification_cooldown_active,
    monitoring_notifications_snoozed,
)


def test_monitoring_update_accepts_bounded_notification_snooze():
    assert MonitoredUserUpdateModel(snooze_minutes=30).snooze_minutes == 30
    assert MonitoredUserUpdateModel(snooze_minutes=0).snooze_minutes == 0

    with pytest.raises(ValidationError):
        MonitoredUserUpdateModel(snooze_minutes=-1)

    with pytest.raises(ValidationError):
        MonitoredUserUpdateModel(snooze_minutes=10081)


def test_monitoring_update_still_rejects_empty_payload():
    with pytest.raises(ValidationError):
        MonitoredUserUpdateModel()


def test_monitoring_snooze_only_suppresses_notifications_until_deadline():
    now = naive_utcnow()
    monitored_user = SimpleNamespace(
        notification_snoozed_until=now + timedelta(minutes=30)
    )

    assert monitoring_notifications_snoozed(monitored_user, now=now) is True
    assert (
        monitoring_notifications_snoozed(
            monitored_user,
            now=now + timedelta(minutes=31),
        )
        is False
    )

    monitored_user.notification_snoozed_until = None
    assert monitoring_notifications_snoozed(monitored_user, now=now) is False


def test_monitoring_notification_cooldown_validation():
    assert (
        ServerMonitoringSettingsUpdateModel(
            notification_cooldown_minutes=5
        ).notification_cooldown_minutes
        == 5
    )
    assert (
        ServerMonitoringSettingsUpdateModel(
            notification_cooldown_minutes=0
        ).notification_cooldown_minutes
        == 0
    )

    with pytest.raises(ValidationError):
        ServerMonitoringSettingsUpdateModel(notification_cooldown_minutes=-1)

    with pytest.raises(ValidationError):
        ServerMonitoringSettingsUpdateModel(notification_cooldown_minutes=1441)


def test_monitoring_notification_cooldown_is_per_user_and_time_bounded():
    now = naive_utcnow()
    monitored_user = SimpleNamespace(
        last_notification_at=now - timedelta(minutes=2)
    )

    assert (
        monitoring_notification_cooldown_active(
            monitored_user,
            5,
            now=now,
        )
        is True
    )
    assert (
        monitoring_notification_cooldown_active(
            monitored_user,
            2,
            now=now,
        )
        is False
    )
    assert (
        monitoring_notification_cooldown_active(
            monitored_user,
            0,
            now=now,
        )
        is False
    )
