import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from api.models.user_profiles import NicknameLogModel
from api.routers import moderation_users as moderation_users_api
from src.db.models import PastNickname
from src.modules import nickname_history


def _member(*, nickname: str | None, display_name: str, guild=None):
    guild = guild or SimpleNamespace(id=123, name="Test server")
    return SimpleNamespace(
        id=456,
        bot=False,
        guild=guild,
        nick=nickname,
        display_name=display_name,
        global_name="Global name",
        name="account-name",
    )


def _install_fake_persistence(monkeypatch, *, latest: PastNickname | None = None):
    result = SimpleNamespace(first=Mock(return_value=latest))
    session = SimpleNamespace(
        exec=AsyncMock(return_value=result),
        add=Mock(),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def fake_get_async_session():
        yield session

    check_server = AsyncMock()
    check_user = AsyncMock()
    monkeypatch.setattr(nickname_history, "get_async_session", fake_get_async_session)
    monkeypatch.setattr(nickname_history, "check_if_server_exists", check_server)
    monkeypatch.setattr(nickname_history, "check_if_user_exists", check_user)
    return session, check_server, check_user


def test_records_previous_server_nickname_and_refreshes_current_membership(monkeypatch) -> None:
    session, check_server, check_user = _install_fake_persistence(monkeypatch)
    before = _member(nickname="Old nickname", display_name="Old nickname")
    after = _member(nickname="New nickname", display_name="New nickname")

    recorded = asyncio.run(nickname_history.record_member_nickname_change(before, after))

    assert recorded is True
    check_server.assert_awaited_once_with(after.guild, session)
    check_user.assert_awaited_once_with(after, after.guild, session)
    session.commit.assert_awaited_once()
    saved = session.add.call_args.args[0]
    assert saved.user_id == after.id
    assert saved.server_id == after.guild.id
    assert saved.server_name == after.guild.name
    assert saved.discord_name == "Old nickname"


def test_records_server_nickname_when_it_is_removed(monkeypatch) -> None:
    session, _, _ = _install_fake_persistence(monkeypatch)
    before = _member(nickname="Old nickname", display_name="Old nickname")
    after = _member(nickname=None, display_name="Global name")

    recorded = asyncio.run(nickname_history.record_member_nickname_change(before, after))

    assert recorded is True
    saved = session.add.call_args.args[0]
    assert saved.discord_name == "Old nickname"


def test_first_server_nickname_records_the_previous_global_name(monkeypatch) -> None:
    session, _, _ = _install_fake_persistence(monkeypatch)
    before = _member(nickname=None, display_name="Old global name")
    after = _member(nickname="First server nickname", display_name="First server nickname")

    recorded = asyncio.run(nickname_history.record_member_nickname_change(before, after))

    assert recorded is True
    saved = session.add.call_args.args[0]
    assert saved.discord_name == "Old global name"


def test_ignores_member_updates_without_a_nickname_change(monkeypatch) -> None:
    get_session = Mock(side_effect=AssertionError("database should not be opened"))
    monkeypatch.setattr(nickname_history, "get_async_session", get_session)
    before = _member(nickname="Same nickname", display_name="Same nickname")
    after = _member(nickname="Same nickname", display_name="Same nickname")

    recorded = asyncio.run(nickname_history.record_member_nickname_change(before, after))

    assert recorded is False
    get_session.assert_not_called()


def test_does_not_duplicate_the_latest_record(monkeypatch) -> None:
    latest = PastNickname(
        user_id=456,
        discord_name="Old nickname",
        server_name="Test server",
        server_id=123,
    )
    session, _, _ = _install_fake_persistence(monkeypatch, latest=latest)
    before = _member(nickname="Old nickname", display_name="Old nickname")
    after = _member(nickname="New nickname", display_name="New nickname")

    recorded = asyncio.run(nickname_history.record_member_nickname_change(before, after))

    assert recorded is False
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


def test_records_previous_global_name_for_members_without_server_nicknames(monkeypatch) -> None:
    session, _, _ = _install_fake_persistence(monkeypatch)
    member = _member(nickname=None, display_name="New global name")
    member.guild.get_member = Mock(return_value=member)
    before = SimpleNamespace(id=member.id, bot=False, display_name="Old global name")
    after = SimpleNamespace(id=member.id, bot=False, display_name="New global name")

    recorded = asyncio.run(
        nickname_history.record_user_display_name_change(before, after, [member.guild])
    )

    assert recorded == 1
    saved = session.add.call_args.args[0]
    assert saved.discord_name == "Old global name"


def test_global_display_name_does_not_override_a_server_nickname(monkeypatch) -> None:
    get_session = Mock(side_effect=AssertionError("database should not be opened"))
    monkeypatch.setattr(nickname_history, "get_async_session", get_session)
    member = _member(nickname="Server nickname", display_name="Server nickname")
    member.guild.get_member = Mock(return_value=member)
    before = SimpleNamespace(id=member.id, bot=False, display_name="Old global name")
    after = SimpleNamespace(id=member.id, bot=False, display_name="New global name")

    recorded = asyncio.run(
        nickname_history.record_user_display_name_change(before, after, [member.guild])
    )

    assert recorded == 0
    get_session.assert_not_called()


def test_manual_history_log_does_not_replace_the_current_nickname(monkeypatch) -> None:
    result = SimpleNamespace(first=Mock(return_value=None))
    session = SimpleNamespace(
        exec=AsyncMock(return_value=result),
        add=Mock(),
        flush=AsyncMock(),
        refresh=AsyncMock(),
    )
    server = SimpleNamespace(server_name="Test server")
    membership = SimpleNamespace(server_nickname="Current nickname")
    get_server = AsyncMock(return_value=server)
    get_membership = AsyncMock(return_value=(SimpleNamespace(), membership))
    monkeypatch.setattr(moderation_users_api, "get_or_create_server_record", get_server)
    monkeypatch.setattr(moderation_users_api, "get_or_create_user_membership", get_membership)

    record = asyncio.run(
        moderation_users_api.log_user_nickname(
            server_id=123,
            user_id=456,
            body=NicknameLogModel(nickname="Past nickname"),
            session=session,
        )
    )

    assert record.nickname == "Past nickname"
    assert membership.server_nickname == "Current nickname"
    assert "server_nickname" not in get_membership.await_args.kwargs
