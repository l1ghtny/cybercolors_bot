import datetime

import pytest
from pydantic import ValidationError

from api.models.birthdays import BirthdayWriteModel
from src.modules.birthdays_module.hourly_check import check_birthday_redone


def test_birthday_timezone_accepts_iana_name_and_normalizes_blank():
    model = BirthdayWriteModel(day=7, month=11, timezone=" Europe/Moscow ")
    blank = BirthdayWriteModel(day=7, month=11, timezone=" ")

    assert model.timezone == "Europe/Moscow"
    assert blank.timezone is None


def test_birthday_timezone_rejects_unknown_name():
    with pytest.raises(ValidationError):
        BirthdayWriteModel(day=7, month=11, timezone="Mars/Olympus")


def test_birthday_current_time_uses_local_timezone_without_external_api(monkeypatch):
    class FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 1, 12, 30, tzinfo=datetime.timezone.utc).astimezone(tz)

    monkeypatch.setattr(check_birthday_redone.datetime, "datetime", FixedDatetime)

    current_time = check_birthday_redone.get_user_current_time("Europe/Moscow")

    assert current_time is not None
    assert current_time.hour == 15
    assert current_time.tzinfo is not None


def test_birthday_current_time_returns_none_for_invalid_timezone():
    assert check_birthday_redone.get_user_current_time("Mars/Olympus") is None
