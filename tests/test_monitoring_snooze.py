from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.models.monitoring import MonitoredUserUpdateModel
from api.services.moderation_core import naive_utcnow
from api.services.monitoring_service import monitoring_notifications_snoozed


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
