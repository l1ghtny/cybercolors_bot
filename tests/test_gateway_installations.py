import asyncio
from datetime import datetime, timezone

from api.routers.auth import _to_auth_guild_payload
from api.services.discord_profiles import (
    CYBERCOLORS_PROFILE,
    MODRAL_PROFILE,
    cache_server_profile,
    clear_server_profile_cache,
    profile_key_for_server_id,
)
from api.services.gateway_installations import (
    assign_primary_gateway,
    record_gateway_presence,
)
from src.db.models import Server, ServerGatewayInstallation


class FakeSession:
    def __init__(self, server: Server | None = None):
        self.servers = {int(server.server_id): server} if server else {}
        self.installations: dict[tuple[int, str], ServerGatewayInstallation] = {}

    async def get(self, model, key):
        if model is Server:
            return self.servers.get(int(key))
        if model is ServerGatewayInstallation:
            server_id, profile_key = key
            return self.installations.get((int(server_id), profile_key))
        raise AssertionError(f"Unexpected model: {model}")

    def add(self, value):
        if isinstance(value, Server):
            self.servers[int(value.server_id)] = value
        elif isinstance(value, ServerGatewayInstallation):
            self.installations[(int(value.server_id), value.profile_key)] = value
        else:
            raise AssertionError(f"Unexpected value: {value}")

    async def flush(self):
        return None


def test_secondary_installation_does_not_replace_primary_gateway():
    observed_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    server = Server(
        server_id=123,
        server_name="Pilot",
        bot_profile=MODRAL_PROFILE,
        bot_active=True,
    )
    session = FakeSession(server)

    primary = asyncio.run(
        record_gateway_presence(
            session,
            server_id=123,
            server_name="Pilot",
            icon=None,
            profile_key=CYBERCOLORS_PROFILE,
            active=True,
            observed_at=observed_at,
        )
    )

    assert primary == MODRAL_PROFILE
    assert server.bot_profile == MODRAL_PROFILE
    assert server.bot_active is True
    assert session.installations[(123, CYBERCOLORS_PROFILE)].active is True


def test_first_installation_becomes_primary_gateway():
    session = FakeSession()

    primary = asyncio.run(
        record_gateway_presence(
            session,
            server_id=456,
            server_name="Branded pilot",
            icon="https://cdn.example/icon.png",
            profile_key=CYBERCOLORS_PROFILE,
            active=True,
        )
    )

    assert primary == CYBERCOLORS_PROFILE
    assert session.servers[456].bot_profile == CYBERCOLORS_PROFILE
    assert session.installations[(456, CYBERCOLORS_PROFILE)].active is True


def test_primary_gateway_can_switch_only_to_an_active_installation():
    server = Server(
        server_id=321,
        server_name="Transition",
        bot_profile=MODRAL_PROFILE,
        bot_active=True,
    )
    session = FakeSession(server)
    session.add(
        ServerGatewayInstallation(
            server_id=321,
            profile_key=CYBERCOLORS_PROFILE,
            active=True,
            joined_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        )
    )

    result = asyncio.run(
        assign_primary_gateway(
            session,
            server_id=321,
            profile_key=CYBERCOLORS_PROFILE,
        )
    )

    assert result.bot_profile == CYBERCOLORS_PROFILE
    assert result.bot_active is True


def test_auth_guild_payload_describes_overlap_and_canonical_dashboard(monkeypatch):
    monkeypatch.setenv("MODRAL_DASHBOARD_ORIGIN", "https://dashboard.modral.app")

    payload = _to_auth_guild_payload(
        {
            "id": "789",
            "name": "Overlap",
            "icon": None,
            "owner": True,
            "permissions": "8",
        },
        surface_profile=CYBERCOLORS_PROFILE,
        primary_profile=MODRAL_PROFILE,
        installed_profiles=(CYBERCOLORS_PROFILE, MODRAL_PROFILE),
    )

    assert payload["installed_gateway_profiles"] == [CYBERCOLORS_PROFILE, MODRAL_PROFILE]
    assert payload["primary_gateway_profile"] == MODRAL_PROFILE
    assert payload["surface_is_primary"] is False
    assert payload["canonical_dashboard_url"] == (
        "https://dashboard.modral.app/dashboard/789/overview"
    )


def test_persisted_primary_profile_overrides_legacy_guild_partition(monkeypatch):
    monkeypatch.setenv("CYBERCOLORS_GUILD_IDS", "")
    clear_server_profile_cache()
    try:
        assert profile_key_for_server_id(999) == MODRAL_PROFILE
        cache_server_profile(999, CYBERCOLORS_PROFILE)
        assert profile_key_for_server_id(999) == CYBERCOLORS_PROFILE
    finally:
        clear_server_profile_cache()
