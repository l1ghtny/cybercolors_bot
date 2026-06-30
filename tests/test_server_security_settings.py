import asyncio
from uuid import uuid4

from api.models.server_security import (
    ServerSecurityCreateNewcomerRoleModel,
    ServerSecurityNewcomerRoleUpdateModel,
)
from api.services.server_security import (
    build_newcomer_role_suggestion,
    create_newcomer_role_and_attach,
    to_server_security_read_model,
    update_newcomer_role,
)
from src.db.database import engine, get_async_session
from src.db.models import Server


def _make_discord_id() -> int:
    return 7_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def test_newcomer_role_suggestion_is_restrictive_by_default():
    suggestion = build_newcomer_role_suggestion()

    assert suggestion.purpose == "newcomer_restricted_role"
    assert suggestion.role_name == "Newcomer"
    assert suggestion.permissions == "0"
    assert suggestion.mentionable is False
    assert suggestion.hoist is False


async def _newcomer_role_settings_scenario(monkeypatch) -> None:
    import api.services.server_security as security_service

    server_id = _make_discord_id()
    role_id = _make_discord_id()
    created_payloads: list[dict] = []

    async def fake_create_guild_role(
        server_id: int,
        name: str,
        *,
        permissions: int | str = 0,
        mentionable: bool = False,
        hoist: bool = False,
        color: int | None = None,
    ) -> dict:
        created_payloads.append(
            {
                "server_id": server_id,
                "name": name,
                "permissions": str(permissions),
                "mentionable": mentionable,
                "hoist": hoist,
                "color": color,
            }
        )
        return {"id": str(role_id), "name": name, "permissions": str(permissions)}

    async def fake_fetch_guild_roles(server_id: int) -> list[dict]:
        return [{"id": str(role_id), "name": "Fresh Paint", "permissions": "0"}]

    monkeypatch.setattr(security_service, "create_guild_role", fake_create_guild_role)
    monkeypatch.setattr(security_service, "fetch_guild_roles", fake_fetch_guild_roles)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="security-server", bot_active=True))
        await session.flush()

        settings = await create_newcomer_role_and_attach(
            session=session,
            server_id=server_id,
            body=ServerSecurityCreateNewcomerRoleModel(
                role_name="Fresh Paint",
                permissions="1024",
                mentionable=True,
                hoist=True,
                color=0x123456,
                enabled=True,
                auto_release_minutes=1440,
            ),
        )
        await session.commit()

        assert settings.newcomer_role_id == role_id
        assert settings.newcomer_restriction_enabled is True
        assert settings.newcomer_auto_release_minutes == 1440
        assert created_payloads == [
            {
                "server_id": server_id,
                "name": "Fresh Paint",
                "permissions": "1024",
                "mentionable": True,
                "hoist": True,
                "color": 0x123456,
            }
        ]

        updated = await update_newcomer_role(
            session=session,
            server_id=server_id,
            body=ServerSecurityNewcomerRoleUpdateModel(
                role_id=str(role_id),
                enabled=False,
                auto_release_minutes=60,
            ),
        )
        await session.commit()

        assert updated.newcomer_restriction_enabled is False
        assert updated.newcomer_auto_release_minutes == 60

        read_model = await to_server_security_read_model(server_id, updated)
        assert read_model.newcomer_role_id == str(role_id)
        assert read_model.newcomer_role_name == "Fresh Paint"
        assert read_model.newcomer_restriction_enabled is False
        assert read_model.newcomer_auto_release_minutes == 60

        manual_release = await update_newcomer_role(
            session=session,
            server_id=server_id,
            body=ServerSecurityNewcomerRoleUpdateModel(auto_release_minutes=0),
        )
        await session.commit()
        assert manual_release.newcomer_auto_release_minutes is None

    await engine.dispose()


def test_newcomer_role_create_and_update_settings(monkeypatch):
    asyncio.run(_newcomer_role_settings_scenario(monkeypatch))
