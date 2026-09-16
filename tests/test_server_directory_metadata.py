import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from api.services import server_directory
from src.db.models import Server


@pytest.mark.parametrize("saved_name", [None, "old-birthdays"])
def test_metadata_resolves_current_birthday_channel_name(monkeypatch, saved_name):
    server = Server(
        server_id=123,
        birthday_channel_id=456,
        birthday_channel_name=saved_name,
    )
    session = AsyncMock()
    session.get.return_value = server
    session.exec.return_value = Mock(one=Mock(return_value=10))
    monkeypatch.setattr(server_directory, "fetch_guild_metadata", AsyncMock(return_value={}))
    fetch_channel = AsyncMock(return_value={"id": "456", "name": "🎂birthdays"})
    monkeypatch.setattr(server_directory, "fetch_channel", fetch_channel)

    metadata = asyncio.run(server_directory.build_server_metadata(session, 123))

    assert metadata.birthday_channel_id == "456"
    assert metadata.birthday_channel_name == "🎂birthdays"
    fetch_channel.assert_awaited_once_with(123, 456)
    assert server.birthday_channel_name == saved_name


@pytest.mark.parametrize("saved_name", [None, "saved-birthdays"])
@pytest.mark.parametrize("unavailable", [None, RuntimeError("Discord unavailable")])
def test_metadata_preserves_fallback_when_birthday_channel_is_unavailable(
    monkeypatch, saved_name, unavailable
):
    session = AsyncMock()
    session.get.return_value = Server(
        server_id=123,
        birthday_channel_id=456,
        birthday_channel_name=saved_name,
    )
    session.exec.return_value = Mock(one=Mock(return_value=10))
    monkeypatch.setattr(server_directory, "fetch_guild_metadata", AsyncMock(return_value={}))
    monkeypatch.setattr(
        server_directory, "fetch_channel", AsyncMock(return_value=None, side_effect=unavailable)
    )

    metadata = asyncio.run(server_directory.build_server_metadata(session, 123))

    assert metadata.birthday_channel_id == "456"
    assert metadata.birthday_channel_name == saved_name
    assert metadata.member_count == 10


@pytest.mark.parametrize("server", [None, Server(server_id=123)])
def test_metadata_skips_channel_lookup_without_birthday_channel(monkeypatch, server):
    session = AsyncMock()
    session.get.return_value = server
    session.exec.return_value = Mock(one=Mock(return_value=0))
    monkeypatch.setattr(server_directory, "fetch_guild_metadata", AsyncMock(return_value={}))
    fetch_channel = AsyncMock()
    monkeypatch.setattr(server_directory, "fetch_channel", fetch_channel)

    metadata = asyncio.run(server_directory.build_server_metadata(session, 123))

    assert metadata.birthday_channel_id is None
    assert metadata.birthday_channel_name is None
    fetch_channel.assert_not_awaited()
