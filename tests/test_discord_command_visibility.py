import asyncio

import httpx
import pytest
from pydantic import ValidationError

from api.models.discord_command_visibility import (
    DiscordCommandPermissionOverwriteModel,
    DiscordCommandVisibilityTargetUpdateModel,
    DiscordCommandVisibilityWriteModel,
)
from api.services import discord_command_visibility as visibility


def test_visibility_update_rejects_duplicate_subjects_and_overwrite_limit():
    with pytest.raises(ValidationError, match="Duplicate Discord permission subjects"):
        DiscordCommandVisibilityTargetUpdateModel(
            target_id="123",
            target_kind="command",
            permissions=[
                DiscordCommandPermissionOverwriteModel(id="456", type="role", permission=True),
                DiscordCommandPermissionOverwriteModel(id="456", type="role", permission=False),
            ],
        )

    with pytest.raises(ValidationError, match="at most 100"):
        DiscordCommandVisibilityTargetUpdateModel(
            target_id="123",
            target_kind="command",
            permissions=[
                DiscordCommandPermissionOverwriteModel(id=str(10_000 + index), type="role", permission=True)
                for index in range(101)
            ],
        )


def test_visibility_write_rejects_duplicate_targets():
    update = DiscordCommandVisibilityTargetUpdateModel(target_id="123", target_kind="command", permissions=[])
    with pytest.raises(ValidationError, match="Duplicate Discord command visibility targets"):
        DiscordCommandVisibilityWriteModel(updates=[update, update])


def test_nested_mod_commands_are_displayed_but_share_one_native_target():
    children = visibility._children(
        {
            "name": "mod",
            "options": [
                {"name": "warn", "description": "Warn a member", "type": 1},
                {
                    "name": "cases",
                    "type": 2,
                    "options": [{"name": "show", "description": "Show a case", "type": 1}],
                },
            ],
        },
        "999",
        {"mod warn": ["moderation.actions.apply.warn"]},
    )

    assert [child.qualified_name for child in children] == ["/mod warn", "/mod cases show"]
    assert {child.native_target_id for child in children} == {"999"}
    assert all(not child.independently_configurable for child in children)
    assert children[0].required_rbac_permissions == ["moderation.actions.apply.warn"]


def test_discord_permission_type_numbers_normalize_to_role_user_and_channel():
    overwrites = visibility._overwrites(
        [
            {"id": "1", "type": 1, "permission": True},
            {"id": "2", "type": 2, "permission": False},
            {"id": "3", "type": 3, "permission": True},
        ]
    )
    assert [(item.id, item.type, item.permission) for item in overwrites] == [
        ("1", "role", True),
        ("2", "user", False),
        ("3", "channel", True),
    ]


def test_visibility_rejects_mismatched_bot_and_oauth_applications(monkeypatch):
    async def fake_get(_client, path, _headers):
        assert path == "/oauth2/applications/@me"
        return {"id": "1067841289527242772"}

    monkeypatch.setattr(visibility, "_discord_get", fake_get)
    with pytest.raises(visibility.DiscordVisibilityError, match="DISCORD_CLIENT_ID"):
        asyncio.run(visibility._assert_bot_matches_application(object(), "1067156290335428659"))


def test_native_preflight_accepts_owner_admin_or_manage_guild_plus_roles(monkeypatch):
    async def capabilities_for(guild: dict):
        async def fake_get(_client, path, _headers, **_kwargs):
            if path == "/oauth2/@me":
                return {"scopes": [visibility.COMMAND_PERMISSION_SCOPE]}
            return [guild]

        monkeypatch.setattr(visibility, "_discord_get", fake_get)
        return await visibility._capabilities(object(), "token", 123)

    assert asyncio.run(capabilities_for({"id": "123", "owner": True, "permissions": "0"})) == (True, True)
    assert asyncio.run(capabilities_for({"id": "123", "permissions": str(visibility.ADMINISTRATOR)})) == (True, True)
    assert asyncio.run(capabilities_for({"id": "123", "permissions": str(visibility.MANAGE_GUILD | visibility.MANAGE_ROLES)})) == (True, True)
    assert asyncio.run(capabilities_for({"id": "123", "permissions": str(visibility.MANAGE_GUILD)})) == (True, False)


def test_discord_get_can_surface_oauth_reconnect_errors():
    async def run():
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(401, json={"message": "401: Unauthorized"})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(visibility.DiscordVisibilityError) as captured:
                await visibility._discord_get(
                    client,
                    "/oauth2/@me",
                    {"Authorization": "Bearer expired"},
                    error_code="discord_oauth_reconnect_required",
                    error_detail="Reconnect command management.",
                    error_status_code=401,
                )
        return captured.value

    error = asyncio.run(run())
    assert error.code == "discord_oauth_reconnect_required"
    assert error.status_code == 401
    assert error.detail == "Reconnect command management."
