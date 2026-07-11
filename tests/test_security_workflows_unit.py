import asyncio

from api.models.server_security import ServerSecurityLockdownUpdateModel
from api.services.ai_settings import can_invoke_answer_flow
from api.services.server_security import apply_lockdown_state
from src.db.models import ServerAISettings, ServerSecuritySettings


def test_disabled_ai_companion_blocks_answer_flow_without_losing_routing():
    settings = ServerAISettings(
        server_id=1,
        answer_enabled=False,
        answer_channel_mode="all",
    )

    assert can_invoke_answer_flow(settings, channel_id=10, role_ids=[]) is False
    assert settings.answer_channel_mode == "all"


def test_lockdown_applies_and_restores_channel_slowmode(monkeypatch):
    async def scenario():
        settings = ServerSecuritySettings(
            server_id=1,
            verified_role_id=2,
            normal_permissions=100,
            lockdown_permissions=10,
        )
        role_updates: list[tuple[int, bool]] = []
        slowmode_updates: list[tuple[int, int]] = []

        class FakeSession:
            def add(self, item):
                return None

            async def flush(self):
                return None

            async def refresh(self, item):
                return None

        async def fake_get_or_create(*args, **kwargs):
            return settings

        async def fake_fetch_channels(server_id):
            assert server_id == 1
            return [{"id": "20", "type": 0, "rate_limit_per_user": 5}]

        async def fake_update_role(*, permissions, bypass_security_pause, **kwargs):
            role_updates.append((permissions, bypass_security_pause))
            return {}

        async def fake_update_slowmode(channel_id, seconds):
            slowmode_updates.append((channel_id, seconds))
            return {}

        import api.services.server_security as service

        monkeypatch.setattr(service, "get_or_create_server_security_settings", fake_get_or_create)
        monkeypatch.setattr(service, "fetch_guild_channels", fake_fetch_channels)
        monkeypatch.setattr(service, "update_guild_role_permissions", fake_update_role)
        monkeypatch.setattr(service, "update_channel_slowmode", fake_update_slowmode)

        await apply_lockdown_state(
            session=FakeSession(),
            server_id=1,
            body=ServerSecurityLockdownUpdateModel(
                enabled=True,
                slowmode_seconds=30,
                channel_ids=["20"],
                pause_public_responses=True,
                pause_role_mutations=True,
                reason="incident",
            ),
        )

        assert settings.lockdown_enabled is True
        assert settings.lockdown_slowmode_previous == {"20": 5}
        assert settings.public_bot_responses_paused is True
        assert settings.role_mutations_paused is True
        assert role_updates == [(10, True)]
        assert slowmode_updates == [(20, 30)]

        await apply_lockdown_state(
            session=FakeSession(),
            server_id=1,
            body=ServerSecurityLockdownUpdateModel(enabled=False),
        )

        assert settings.lockdown_enabled is False
        assert settings.lockdown_slowmode_previous == {}
        assert settings.public_bot_responses_paused is False
        assert settings.role_mutations_paused is False
        assert role_updates == [(10, True), (100, True)]
        assert slowmode_updates == [(20, 30), (20, 5)]

    asyncio.run(scenario())
