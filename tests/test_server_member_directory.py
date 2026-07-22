import asyncio

from api.services import discord_guilds, server_directory


def _member(
    user_id: int,
    *,
    username: str,
    nick: str | None = None,
    roles: list[int] | None = None,
    bot: bool = False,
    joined_at: str | None = "2026-07-09T12:00:00+00:00",
) -> dict:
    return {
        "user": {
            "id": str(user_id),
            "username": username,
            "global_name": username.title(),
            "avatar": f"avatar-{user_id}",
            "bot": bot,
        },
        "nick": nick,
        "roles": [str(role_id) for role_id in (roles or [])],
        "joined_at": joined_at,
    }


def test_fetch_all_guild_members_paginates(monkeypatch):
    calls: list[dict] = []
    first_page = [_member(index, username=f"user-{index}") for index in range(1, 1001)]
    second_page = [_member(1001, username="last-user")]

    async def fake_discord_get(path: str, params: dict | None = None):
        calls.append({"path": path, "params": params})
        return first_page if len(calls) == 1 else second_page

    monkeypatch.setattr(discord_guilds, "_discord_get", fake_discord_get)

    result = asyncio.run(discord_guilds.fetch_all_guild_members(123))

    assert len(result) == 1001
    assert calls == [
        {"path": "/guilds/123/members", "params": {"limit": 1000}},
        {
            "path": "/guilds/123/members",
            "params": {"limit": 1000, "after": "1000"},
        },
    ]


def test_query_server_members_filters_roles_and_paginates(monkeypatch):
    members = [
        _member(1, username="charlie", roles=[10]),
        _member(2, username="alpha", nick="Moderator Alpha", roles=[20, 30]),
        _member(3, username="bravo", roles=[20]),
    ]

    async def fake_cached_members(server_id: int):
        assert server_id == 123
        return members

    monkeypatch.setattr(server_directory, "_cached_guild_members", fake_cached_members)

    page = asyncio.run(
        server_directory.query_server_members(
            123,
            role_ids=[20],
            offset=1,
            limit=1,
        )
    )

    assert page.total == 2
    assert page.offset == 1
    assert page.limit == 1
    assert [item.user_id for item in page.items] == ["2"]
    assert page.items[0].role_ids == ["20", "30"]


def test_query_server_members_searches_nickname_username_and_id(monkeypatch):
    members = [
        _member(101, username="first-user", nick="Visible Nick", roles=[10]),
        _member(202, username="second-user", roles=[20]),
    ]

    async def fake_cached_members(server_id: int):
        return members

    monkeypatch.setattr(server_directory, "_cached_guild_members", fake_cached_members)

    nickname_page = asyncio.run(server_directory.query_server_members(123, search="visible"))
    username_page = asyncio.run(server_directory.query_server_members(123, search="SECOND"))
    id_page = asyncio.run(server_directory.query_server_members(123, search="101"))

    assert [item.user_id for item in nickname_page.items] == ["101"]
    assert [item.user_id for item in username_page.items] == ["202"]
    assert [item.user_id for item in id_page.items] == ["101"]


def test_query_server_members_sorts_by_name_and_join_date(monkeypatch):
    members = [
        _member(
            1,
            username="charlie",
            joined_at="2025-01-01T12:00:00+00:00",
        ),
        _member(
            2,
            username="alpha",
            joined_at="2026-01-01T12:00:00+00:00",
        ),
        _member(3, username="bravo", joined_at=None),
    ]

    async def fake_cached_members(server_id: int):
        return members

    monkeypatch.setattr(server_directory, "_cached_guild_members", fake_cached_members)

    name_desc = asyncio.run(
        server_directory.query_server_members(123, sort="name_desc")
    )
    joined_newest = asyncio.run(
        server_directory.query_server_members(123, sort="joined_newest")
    )
    joined_oldest = asyncio.run(
        server_directory.query_server_members(123, sort="joined_oldest")
    )

    assert [item.user_id for item in name_desc.items] == ["1", "3", "2"]
    assert [item.user_id for item in joined_newest.items] == ["2", "1", "3"]
    assert [item.user_id for item in joined_oldest.items] == ["1", "2", "3"]


def test_query_server_members_sorts_owner_and_staff_first(monkeypatch):
    members = [
        _member(1, username="regular"),
        _member(2, username="moderator", roles=[20]),
        _member(3, username="owner"),
        _member(4, username="admin", roles=[10]),
    ]

    async def fake_cached_members(server_id: int):
        return members

    async def fake_metadata(server_id: int):
        return {"owner_id": "3"}

    async def fake_roles(server_id: int):
        return [
            {"id": "10", "name": "Admin", "position": 10, "permissions": str(1 << 3), "managed": False},
            {"id": "20", "name": "Moderator", "position": 5, "permissions": str(1 << 40), "managed": False},
        ]

    monkeypatch.setattr(server_directory, "_cached_guild_members", fake_cached_members)
    monkeypatch.setattr(server_directory, "fetch_guild_metadata", fake_metadata)
    monkeypatch.setattr(server_directory, "fetch_guild_roles", fake_roles)

    page = asyncio.run(server_directory.query_server_members(123, sort="staff_first"))

    assert [item.user_id for item in page.items] == ["3", "4", "2", "1"]
    assert page.items[0].is_owner is True
    assert page.items[1].priority_role_id == "10"
    assert page.items[2].priority_role_id == "20"


def test_query_server_members_respects_configured_role_order(monkeypatch):
    members = [
        _member(1, username="first-role", roles=[10]),
        _member(2, username="second-role", roles=[20]),
    ]

    async def fake_cached_members(server_id: int):
        return members

    async def fake_metadata(server_id: int):
        return {}

    async def fake_roles(server_id: int):
        return [
            {"id": "10", "name": "First", "position": 10, "permissions": "0", "managed": False},
            {"id": "20", "name": "Second", "position": 5, "permissions": "0", "managed": False},
        ]

    monkeypatch.setattr(server_directory, "_cached_guild_members", fake_cached_members)
    monkeypatch.setattr(server_directory, "fetch_guild_metadata", fake_metadata)
    monkeypatch.setattr(server_directory, "fetch_guild_roles", fake_roles)

    page = asyncio.run(
        server_directory.query_server_members(
            123,
            sort="staff_first",
            priority_role_ids=[20, 10],
        )
    )

    assert [item.user_id for item in page.items] == ["2", "1"]


def test_list_server_emojis_sorts_available_items_by_name(monkeypatch):
    async def fake_emojis(server_id: int):
        assert server_id == 123
        return [
            {"id": "2", "name": "zeta", "animated": True, "available": False},
            {"id": "1", "name": "Alpha", "animated": False, "available": True},
        ]

    monkeypatch.setattr(server_directory, "fetch_guild_emojis", fake_emojis)
    emojis = asyncio.run(server_directory.list_server_emojis(123))

    assert [emoji.id for emoji in emojis] == ["1", "2"]
    assert emojis[0].name == "Alpha"
    assert emojis[1].animated is True
