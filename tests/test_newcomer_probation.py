import asyncio

import pytest
from fastapi import HTTPException

from api.services import newcomer_probation
from src.db.models import ServerSecuritySettings


def _settings(**overrides) -> ServerSecuritySettings:
    values = {
        "server_id": 9_999_999_999_999_001,
        "newcomer_role_id": 101,
        "newcomer_member_role_id": 202,
    }
    values.update(overrides)
    return ServerSecuritySettings(**values)


def test_newcomer_restriction_mask_respects_each_toggle():
    settings = _settings(
        newcomer_block_bot_commands=True,
        newcomer_block_attachments=True,
        newcomer_block_embeds=True,
        newcomer_block_streaming=True,
        newcomer_block_threads=True,
    )

    text_mask = newcomer_probation.newcomer_restriction_mask(settings, 0)
    voice_mask = newcomer_probation.newcomer_restriction_mask(settings, 2)

    assert text_mask & newcomer_probation.PERMISSION_USE_APPLICATION_COMMANDS
    assert text_mask & newcomer_probation.PERMISSION_ATTACH_FILES
    assert text_mask & newcomer_probation.PERMISSION_EMBED_LINKS
    assert text_mask & newcomer_probation.PERMISSION_CREATE_PUBLIC_THREADS
    assert text_mask & newcomer_probation.PERMISSION_CREATE_PRIVATE_THREADS
    assert not text_mask & newcomer_probation.PERMISSION_STREAM
    assert voice_mask == newcomer_probation.PERMISSION_STREAM


async def _promotion_scenario(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def fake_add(server_id: int, user_id: int, role_id: int) -> None:
        assert (server_id, user_id) == (1, 2)
        calls.append(("add", role_id))

    async def fake_remove(server_id: int, user_id: int, role_id: int) -> None:
        assert (server_id, user_id) == (1, 2)
        calls.append(("remove", role_id))

    monkeypatch.setattr(newcomer_probation, "add_guild_member_role", fake_add)
    monkeypatch.setattr(newcomer_probation, "remove_guild_member_role", fake_remove)

    await newcomer_probation.promote_newcomer_member(
        server_id=1,
        user_id=2,
        settings=_settings(newcomer_role_id=11, newcomer_member_role_id=22),
        current_role_ids={11},
    )

    assert calls == [("add", 22), ("remove", 11)]


def test_promote_newcomer_member_adds_member_before_removing_newcomer(monkeypatch):
    asyncio.run(_promotion_scenario(monkeypatch))


def test_newcomer_and_member_roles_must_be_different():
    with pytest.raises(HTTPException, match="newcomer and member roles"):
        newcomer_probation.assert_newcomer_role_configuration(
            _settings(newcomer_role_id=101, newcomer_member_role_id=101),
        )


async def _template_scenario(monkeypatch):
    applied_permissions: list[tuple[int, int]] = []
    applied_overwrites: list[tuple[int, int, int, int]] = []

    async def fake_roles(server_id: int) -> list[dict]:
        assert server_id == 1
        return [{"id": "202", "permissions": str(1 << 8)}]

    async def fake_channels(server_id: int) -> list[dict]:
        assert server_id == 1
        return [
            {
                "id": "300",
                "type": 0,
                "permission_overwrites": [
                    {"id": "202", "type": 0, "allow": str(1 << 14), "deny": "0"},
                ],
            },
            {"id": "400", "type": 2, "permission_overwrites": []},
            {"id": "500", "type": 99, "permission_overwrites": []},
        ]

    async def fake_permissions(*, server_id: int, role_id: int, permissions: int) -> None:
        assert server_id == 1
        assert role_id == 101
        applied_permissions.append((role_id, permissions))

    async def fake_overwrite(channel_id: int, role_id: int, *, allow: int, deny: int) -> None:
        applied_overwrites.append((channel_id, role_id, allow, deny))

    monkeypatch.setattr(newcomer_probation, "fetch_guild_roles", fake_roles)
    monkeypatch.setattr(newcomer_probation, "fetch_guild_channels", fake_channels)
    monkeypatch.setattr(newcomer_probation, "update_guild_role_permissions", fake_permissions)
    monkeypatch.setattr(newcomer_probation, "update_channel_role_overwrite", fake_overwrite)

    settings = _settings(
        newcomer_block_bot_commands=False,
        newcomer_block_attachments=True,
        newcomer_block_embeds=True,
        newcomer_block_streaming=True,
        newcomer_block_threads=False,
    )
    updated, skipped = await newcomer_probation.apply_newcomer_restriction_template(
        server_id=1,
        settings=settings,
    )

    assert applied_permissions == [(101, 1 << 8)]
    assert updated == 2
    assert skipped == 1
    assert applied_overwrites[0] == (
        300,
        101,
        0,
        newcomer_probation.PERMISSION_ATTACH_FILES | newcomer_probation.PERMISSION_EMBED_LINKS,
    )
    assert applied_overwrites[1] == (400, 101, 0, newcomer_probation.PERMISSION_STREAM)


def test_apply_newcomer_restriction_template_copies_access_and_denies_selected_bits(monkeypatch):
    asyncio.run(_template_scenario(monkeypatch))
