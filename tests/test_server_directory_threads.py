import asyncio

from api.services import server_directory


def test_list_server_channels_includes_active_threads_and_recent_forum_posts(monkeypatch):
    async def fake_channels(_server_id: int) -> list[dict]:
        return [
            {"id": "10", "name": "Community", "type": 4, "position": 0},
            {"id": "20", "name": "general", "type": 0, "position": 1, "parent_id": "10"},
            {"id": "30", "name": "ideas", "type": 15, "position": 2, "parent_id": "10"},
        ]

    async def fake_active_threads(_server_id: int) -> list[dict]:
        return [
            {
                "id": "21",
                "name": "Active discussion",
                "type": 11,
                "parent_id": "20",
                "thread_metadata": {"archived": False, "locked": False},
            },
            {
                "id": "31",
                "name": "Active idea",
                "type": 11,
                "parent_id": "30",
                "thread_metadata": {"archived": False, "locked": False},
            },
        ]

    archived_calls: list[tuple[int, int]] = []

    async def fake_archived_threads(channel_id: int, limit: int = 50) -> list[dict]:
        archived_calls.append((channel_id, limit))
        return [
            {
                "id": "32",
                "name": "Archived idea",
                "type": 11,
                "parent_id": "30",
                "thread_metadata": {"archived": True, "locked": False},
            },
            {
                "id": "33",
                "name": "Locked idea",
                "type": 11,
                "parent_id": "30",
                "thread_metadata": {"archived": True, "locked": True},
            },
        ]

    monkeypatch.setattr(server_directory, "fetch_guild_channels", fake_channels)
    monkeypatch.setattr(server_directory, "fetch_active_guild_threads", fake_active_threads)
    monkeypatch.setattr(server_directory, "fetch_public_archived_threads", fake_archived_threads)

    channels = asyncio.run(
        server_directory.list_server_channels(
            123,
            include_threads=True,
            include_archived_threads=True,
        )
    )
    by_id = {channel.id: channel for channel in channels}

    assert set(by_id) == {"20", "21", "31", "32"}
    assert by_id["20"].parent_name == "Community"
    assert by_id["21"].parent_name == "general"
    assert by_id["21"].parent_type == 0
    assert by_id["31"].parent_name == "ideas"
    assert by_id["31"].parent_type == 15
    assert by_id["32"].archived is True
    assert archived_calls == [(30, 50)]


def test_list_server_channels_keeps_thread_discovery_opt_in(monkeypatch):
    async def fake_channels(_server_id: int) -> list[dict]:
        return [{"id": "20", "name": "general", "type": 0, "position": 1}]

    async def unexpected_threads(_server_id: int) -> list[dict]:
        raise AssertionError("thread discovery should be opt in")

    monkeypatch.setattr(server_directory, "fetch_guild_channels", fake_channels)
    monkeypatch.setattr(server_directory, "fetch_active_guild_threads", unexpected_threads)

    channels = asyncio.run(server_directory.list_server_channels(123))

    assert [channel.id for channel in channels] == ["20"]
