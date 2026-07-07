import asyncio
from uuid import uuid4

from api.models.server_temp_voice import (
    ServerTempVoiceCreateTriggerChannelModel,
    ServerTempVoiceSettingsUpdateModel,
)
from api.services.server_temp_voice import (
    create_temp_voice_trigger_channel_and_attach,
    to_server_temp_voice_read_model,
    update_server_temp_voice_settings,
)
from src.db.database import engine, get_async_session
from src.modules.on_voice_state_processing.create_voice_channel import temp_voice_owner_has_allowed_role
from src.db.models import Server, ServerTempVoiceSettings


def _make_discord_id() -> int:
    return 9_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _temp_voice_settings_scenario(monkeypatch) -> None:
    import api.services.server_temp_voice as temp_voice_service

    server_id = _make_discord_id()
    trigger_channel_id = _make_discord_id()
    archive_channel_id = _make_discord_id()
    created_channel_id = _make_discord_id()
    created_payloads: list[dict] = []

    async def fake_fetch_guild_channels(server_id: int) -> list[dict]:
        return [
            {"id": str(trigger_channel_id), "name": "Join to Create", "type": 2},
            {"id": str(archive_channel_id), "name": "voice-archives", "type": 0},
            {"id": str(created_channel_id), "name": "CREATE", "type": 2},
        ]

    async def fake_create_guild_voice_channel(
        server_id: int,
        name: str,
        *,
        category_id: int | str | None = None,
    ) -> dict:
        created_payloads.append({"server_id": server_id, "name": name, "category_id": category_id})
        return {"id": str(created_channel_id), "name": name, "type": 2}

    monkeypatch.setattr(temp_voice_service, "fetch_guild_channels", fake_fetch_guild_channels)
    monkeypatch.setattr(temp_voice_service, "create_guild_voice_channel", fake_create_guild_voice_channel)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="temp-voice-server", bot_active=True))
        await session.flush()

        settings = await update_server_temp_voice_settings(
            session=session,
            server_id=server_id,
            body=ServerTempVoiceSettingsUpdateModel(
                enabled=True,
                trigger_channel_id=str(trigger_channel_id),
                archive_channel_id=str(archive_channel_id),
                archive_post_mode="off",
                channel_name_template="{display_name}'s room",
                owner_manage_channel_enabled=False,
                owner_rename_enabled=True,
                owner_user_limit_enabled=True,
                owner_control_allowed_role_ids=[str(_make_discord_id()), str(_make_discord_id())],
            ),
        )
        await session.commit()

        assert settings.enabled is True
        assert settings.trigger_channel_id == trigger_channel_id
        assert settings.archive_channel_id == archive_channel_id
        assert settings.archive_post_mode == "off"
        assert settings.channel_name_template == "{display_name}'s room"
        assert settings.owner_manage_channel_enabled is False
        assert settings.owner_rename_enabled is True
        assert settings.owner_user_limit_enabled is True
        assert len(settings.owner_control_allowed_role_ids) == 2

        read_model = await to_server_temp_voice_read_model(server_id, settings)
        assert read_model.trigger_channel_name == "Join to Create"
        assert read_model.archive_channel_name == "voice-archives"
        assert read_model.archive_post_mode == "off"
        assert read_model.owner_manage_channel_enabled is False
        assert read_model.owner_rename_enabled is True
        assert read_model.owner_user_limit_enabled is True
        assert read_model.owner_control_allowed_role_ids == settings.owner_control_allowed_role_ids

        created = await create_temp_voice_trigger_channel_and_attach(
            session=session,
            server_id=server_id,
            body=ServerTempVoiceCreateTriggerChannelModel(name="CREATE", category_id=str(_make_discord_id())),
        )
        await session.commit()

        assert created.trigger_channel_id == created_channel_id
        assert created.enabled is True
        assert created_payloads[0]["name"] == "CREATE"

    await engine.dispose()


def test_temp_voice_settings_update_and_create_trigger_channel(monkeypatch):
    asyncio.run(_temp_voice_settings_scenario(monkeypatch))

class _FakeRole:
    def __init__(self, role_id: int):
        self.id = role_id


class _FakeMember:
    def __init__(self, *role_ids: int):
        self.roles = [_FakeRole(role_id) for role_id in role_ids]


def test_temp_voice_owner_role_gate_allows_everyone_when_unconfigured():
    settings = ServerTempVoiceSettings(server_id=_make_discord_id())

    assert temp_voice_owner_has_allowed_role(_FakeMember(), settings) is True


def test_temp_voice_owner_role_gate_requires_matching_role():
    matching_role_id = _make_discord_id()
    settings = ServerTempVoiceSettings(
        server_id=_make_discord_id(),
        owner_control_allowed_role_ids=[str(matching_role_id)],
    )

    assert temp_voice_owner_has_allowed_role(_FakeMember(matching_role_id), settings) is True
    assert temp_voice_owner_has_allowed_role(_FakeMember(_make_discord_id()), settings) is False
