import asyncio
import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.models.birthdays import BirthdayWriteModel
from api.services import birthday_permission_warnings
from src.modules.birthdays_module.hourly_check import check_birthday_redone, check_roles
from src.modules.observability.bot_metrics import (
    BIRTHDAY_ROLE_CLEANUP_PENDING,
    BIRTHDAY_ROLE_CLEANUP_USERS,
    BIRTHDAY_ROLE_REMOVALS,
)


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


def test_add_birthday_role_returns_false_on_discord_permission_error(monkeypatch):
    class FakeDiscordError(Exception):
        pass

    class FakeMember:
        id = 123

        async def add_roles(self, role):
            raise FakeDiscordError("missing permissions")

    monkeypatch.setattr(check_birthday_redone.discord, "Forbidden", FakeDiscordError)
    monkeypatch.setattr(check_birthday_redone.discord, "HTTPException", FakeDiscordError)

    result = asyncio.run(
        check_birthday_redone.add_birthday_role(
            FakeMember(),
            SimpleNamespace(id=456),
            server_id=789,
        )
    )

    assert result is False


def test_send_birthday_greeting_returns_false_on_discord_permission_error(monkeypatch):
    class FakeDiscordError(Exception):
        pass

    class FakeClient:
        async def fetch_channel(self, channel_id):
            raise FakeDiscordError("missing permissions")

    monkeypatch.setattr(check_birthday_redone.discord, "Forbidden", FakeDiscordError)
    monkeypatch.setattr(check_birthday_redone.discord, "HTTPException", FakeDiscordError)

    result = asyncio.run(
        check_birthday_redone.send_birthday_greeting(
            FakeClient(),
            SimpleNamespace(server_id=123, birthday_channel_id=456),
            embed=SimpleNamespace(),
        )
    )

    assert result is False


def test_mark_birthday_processed_sets_timestamp_and_commits():
    class FakeSession:
        def __init__(self):
            self.merged = False
            self.committed = False
            self.refreshed = False

        async def merge(self, birthday):
            self.merged = True

        async def commit(self):
            self.committed = True

        async def refresh(self, birthday):
            self.refreshed = True

    birthday = SimpleNamespace(role_added_at=None)
    session = FakeSession()

    asyncio.run(check_birthday_redone.mark_birthday_processed(session, birthday))

    assert birthday.role_added_at is not None
    assert session.merged is True
    assert session.committed is True
    assert session.refreshed is True


def test_birthday_role_age_accepts_timezone_aware_database_timestamp():
    role_added_at = datetime.datetime(2026, 7, 30, 16, 0, tzinfo=datetime.timezone.utc)
    now = datetime.datetime(2026, 7, 31, 16, 0, tzinfo=datetime.timezone.utc)

    assert check_roles.birthday_role_age(role_added_at, now=now) == datetime.timedelta(days=1)


def test_birthday_role_age_treats_legacy_naive_timestamp_as_utc():
    role_added_at = datetime.datetime(2026, 7, 30, 16, 0)
    now = datetime.datetime(2026, 7, 31, 16, 0, tzinfo=datetime.timezone.utc)

    assert check_roles.birthday_role_age(role_added_at, now=now) == datetime.timedelta(days=1)


def test_birthday_role_check_skips_invalid_timestamp_and_processes_next_record(monkeypatch):
    class FakeResult:
        def all(self):
            return [(invalid_user, invalid_birthday), (valid_user, valid_birthday)]

    class FakeSession:
        def __init__(self):
            self.commits = 0

        async def exec(self, statement):
            return FakeResult()

        async def merge(self, birthday):
            return birthday

        async def commit(self):
            self.commits += 1

    class FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeMember:
        def __init__(self):
            self.removed_roles = []

        async def remove_roles(self, role):
            self.removed_roles.append(role)

    role = SimpleNamespace(id=456, name="birthday")
    member = FakeMember()
    guild = SimpleNamespace(roles=[role], get_member=lambda user_id: member)
    server = SimpleNamespace(birthday_role_id=role.id)
    invalid_user = SimpleNamespace(user_id=1, server_id=123, server=server)
    valid_user = SimpleNamespace(user_id=2, server_id=123, server=server)
    invalid_birthday = SimpleNamespace(role_added_at="not-a-timestamp")
    valid_birthday = SimpleNamespace(
        role_added_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    )
    session = FakeSession()
    client = SimpleNamespace(
        get_user=lambda user_id: SimpleNamespace(name=f"user-{user_id}"),
        get_guild=lambda guild_id: guild,
    )
    monkeypatch.setattr(check_roles, "get_async_session", lambda: FakeSessionContext())

    asyncio.run(check_roles.check_roles(client))

    assert member.removed_roles == [role]
    assert valid_birthday.role_added_at is None
    assert session.commits == 1


def test_birthday_role_check_removes_roles_from_all_servers_before_clearing_timestamp(monkeypatch):
    removed_before = BIRTHDAY_ROLE_REMOVALS.labels(outcome="removed")._value.get()
    completed_before = BIRTHDAY_ROLE_CLEANUP_USERS.labels(outcome="completed")._value.get()
    role_one = SimpleNamespace(id=101, name="birthday-one")
    role_two = SimpleNamespace(id=202, name="birthday-two")

    class FakeMember:
        def __init__(self):
            self.removed_roles = []

        async def remove_roles(self, role):
            self.removed_roles.append(role)

    member_one = FakeMember()
    member_two = FakeMember()
    guilds = {
        11: SimpleNamespace(roles=[role_one], get_member=lambda user_id: member_one),
        22: SimpleNamespace(roles=[role_two], get_member=lambda user_id: member_two),
    }
    birthday = SimpleNamespace(
        role_added_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    )
    memberships = [
        SimpleNamespace(
            user_id=42,
            server_id=11,
            server=SimpleNamespace(birthday_role_id=role_one.id),
        ),
        SimpleNamespace(
            user_id=42,
            server_id=22,
            server=SimpleNamespace(birthday_role_id=role_two.id),
        ),
    ]

    class FakeSession:
        def __init__(self):
            self.merged = []
            self.commits = 0

        async def exec(self, statement):
            return SimpleNamespace(all=lambda: [(membership, birthday) for membership in memberships])

        async def merge(self, item):
            self.merged.append(item)

        async def commit(self):
            assert member_one.removed_roles == [role_one]
            assert member_two.removed_roles == [role_two]
            self.commits += 1

    session = FakeSession()

    class FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    client = SimpleNamespace(get_guild=guilds.get)
    monkeypatch.setattr(check_roles, "get_async_session", lambda: FakeSessionContext())

    asyncio.run(check_roles.check_roles(client))

    assert birthday.role_added_at is None
    assert session.merged == [birthday]
    assert session.commits == 1
    assert BIRTHDAY_ROLE_REMOVALS.labels(outcome="removed")._value.get() == removed_before + 2
    assert BIRTHDAY_ROLE_CLEANUP_USERS.labels(outcome="completed")._value.get() == completed_before + 1
    assert BIRTHDAY_ROLE_CLEANUP_PENDING._value.get() == 0


def test_birthday_role_check_retries_all_servers_if_one_removal_fails(monkeypatch):
    removed_before = BIRTHDAY_ROLE_REMOVALS.labels(outcome="removed")._value.get()
    errors_before = BIRTHDAY_ROLE_REMOVALS.labels(outcome="discord_error")._value.get()
    retries_before = BIRTHDAY_ROLE_CLEANUP_USERS.labels(outcome="retry_pending")._value.get()
    class FakeDiscordError(Exception):
        pass

    monkeypatch.setattr(check_roles.discord, "Forbidden", FakeDiscordError)
    monkeypatch.setattr(check_roles.discord, "HTTPException", FakeDiscordError)

    role_one = SimpleNamespace(id=101, name="birthday-one")
    role_two = SimpleNamespace(id=202, name="birthday-two")

    class FailingMember:
        async def remove_roles(self, role):
            raise FakeDiscordError("missing permissions")

    class SuccessfulMember:
        def __init__(self):
            self.removed_roles = []

        async def remove_roles(self, role):
            self.removed_roles.append(role)

    successful_member = SuccessfulMember()
    guilds = {
        11: SimpleNamespace(roles=[role_one], get_member=lambda user_id: FailingMember()),
        22: SimpleNamespace(roles=[role_two], get_member=lambda user_id: successful_member),
    }
    role_added_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    birthday = SimpleNamespace(role_added_at=role_added_at)
    memberships = [
        SimpleNamespace(
            user_id=42,
            server_id=11,
            server=SimpleNamespace(birthday_role_id=role_one.id),
        ),
        SimpleNamespace(
            user_id=42,
            server_id=22,
            server=SimpleNamespace(birthday_role_id=role_two.id),
        ),
    ]

    class FakeSession:
        def __init__(self):
            self.merged = []
            self.commits = 0

        async def exec(self, statement):
            return SimpleNamespace(all=lambda: [(membership, birthday) for membership in memberships])

        async def merge(self, item):
            self.merged.append(item)

        async def commit(self):
            self.commits += 1

    session = FakeSession()

    class FakeSessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    client = SimpleNamespace(get_guild=guilds.get)
    monkeypatch.setattr(check_roles, "get_async_session", lambda: FakeSessionContext())

    asyncio.run(check_roles.check_roles(client))

    assert successful_member.removed_roles == [role_two]
    assert birthday.role_added_at == role_added_at
    assert session.merged == []
    assert session.commits == 0
    assert BIRTHDAY_ROLE_REMOVALS.labels(outcome="removed")._value.get() == removed_before + 1
    assert BIRTHDAY_ROLE_REMOVALS.labels(outcome="discord_error")._value.get() == errors_before + 1
    assert BIRTHDAY_ROLE_CLEANUP_USERS.labels(outcome="retry_pending")._value.get() == retries_before + 1
    assert BIRTHDAY_ROLE_CLEANUP_PENDING._value.get() == 1


def test_birthday_settings_warning_detects_role_hierarchy_and_permissions(monkeypatch):
    async def fake_bot_user():
        return {"id": "99"}

    async def fake_bot_member(server_id, user_id):
        return {"roles": ["10"]}

    async def fake_roles(server_id):
        return [
            {"id": str(server_id), "name": "@everyone", "permissions": "0", "position": 0},
            {"id": "10", "name": "bot", "permissions": "0", "position": 1},
            {"id": "20", "name": "birthday", "permissions": "0", "position": 2, "managed": False},
        ]

    monkeypatch.setattr(birthday_permission_warnings, "fetch_current_bot_user", fake_bot_user)
    monkeypatch.setattr(birthday_permission_warnings, "fetch_guild_member", fake_bot_member)
    monkeypatch.setattr(birthday_permission_warnings, "fetch_guild_roles", fake_roles)

    warnings = asyncio.run(
        birthday_permission_warnings.build_birthday_settings_warnings(
            SimpleNamespace(server_id=123, birthday_role_id=20, birthday_channel_id=None)
        )
    )

    keys = {warning.key for warning in warnings}
    assert "bot_missing_manage_roles" in keys
    assert "bot_role_too_low" in keys


def test_birthday_settings_warning_detects_channel_permissions(monkeypatch):
    async def fake_bot_user():
        return {"id": "99"}

    async def fake_bot_member(server_id, user_id):
        return {"roles": ["10"]}

    async def fake_roles(server_id):
        return [
            {"id": str(server_id), "name": "@everyone", "permissions": "1024", "position": 0},
            {"id": "10", "name": "bot", "permissions": "0", "position": 1},
        ]

    async def fake_channel(server_id, channel_id):
        return {"id": str(channel_id), "type": 0, "permission_overwrites": []}

    monkeypatch.setattr(birthday_permission_warnings, "fetch_current_bot_user", fake_bot_user)
    monkeypatch.setattr(birthday_permission_warnings, "fetch_guild_member", fake_bot_member)
    monkeypatch.setattr(birthday_permission_warnings, "fetch_guild_roles", fake_roles)
    monkeypatch.setattr(birthday_permission_warnings, "fetch_channel", fake_channel)

    warnings = asyncio.run(
        birthday_permission_warnings.build_birthday_settings_warnings(
            SimpleNamespace(server_id=123, birthday_role_id=None, birthday_channel_id=30)
        )
    )

    assert [warning.key for warning in warnings] == ["bot_missing_channel_permissions"]
