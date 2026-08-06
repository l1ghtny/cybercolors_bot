import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Request

from api.dependencies import server_access
from api.services import dashboard_sessions
from api.services.discord_profiles import (
    CYBERCOLORS_PROFILE,
    MODRAL_PROFILE,
    get_profile,
    invite_url_for_profile,
    profile_for_api_host,
    validate_profile_redirect_uri,
)
from src.db.models import DashboardSession, Server


def _request(host: str, cookie_value: str | None = None) -> Request:
    headers = [(b"host", host.encode("ascii"))]
    if cookie_value is not None:
        headers.append(
            (
                b"cookie",
                f"{dashboard_sessions.SESSION_COOKIE_NAME}={cookie_value}".encode("ascii"),
            )
        )
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_dashboard_hosts_select_independent_discord_applications(monkeypatch):
    monkeypatch.setenv("CYBERCOLORS_DISCORD_CLIENT_ID", "111")
    monkeypatch.setenv("CYBERCOLORS_DISCORD_BOT_TOKEN", "cyber-token")
    monkeypatch.setenv("MODRAL_DISCORD_CLIENT_ID", "222")
    monkeypatch.setenv("MODRAL_DISCORD_BOT_TOKEN", "modral-token")

    cybercolors = profile_for_api_host("cybercolors-api.modral.app")
    modral = profile_for_api_host("api.modral.app")

    assert cybercolors.key == CYBERCOLORS_PROFILE
    assert cybercolors.client_id == "111"
    assert cybercolors.bot_token == "cyber-token"
    assert modral.key == MODRAL_PROFILE
    assert modral.client_id == "222"
    assert modral.bot_token == "modral-token"
    assert "client_id=111" in invite_url_for_profile(cybercolors)
    assert "client_id=222" in invite_url_for_profile(modral)


def test_oauth_redirects_cannot_cross_dashboard_surfaces(monkeypatch):
    monkeypatch.setenv(
        "CYBERCOLORS_DASHBOARD_OAUTH_REDIRECT_URIS",
        "https://cybercolors.modral.app/callback",
    )
    monkeypatch.setenv(
        "MODRAL_DASHBOARD_OAUTH_REDIRECT_URIS",
        "https://dashboard.modral.app/callback",
    )

    assert validate_profile_redirect_uri(
        get_profile(CYBERCOLORS_PROFILE),
        "https://cybercolors.modral.app/callback",
    ) == "https://cybercolors.modral.app/callback"
    with pytest.raises(HTTPException) as exc_info:
        validate_profile_redirect_uri(
            get_profile(CYBERCOLORS_PROFILE),
            "https://dashboard.modral.app/callback",
        )
    assert exc_info.value.status_code == 400


def test_dashboard_session_cannot_be_reused_on_other_application_host():
    cookie_value = "opaque-session-token"
    now = datetime.now(timezone.utc)
    stored = DashboardSession(
        session_token_hash=dashboard_sessions._token_hash(cookie_value),
        discord_user_id=123,
        application_profile=CYBERCOLORS_PROFILE,
        discord_access_token="encrypted",
        discord_token_expires_at=now + timedelta(hours=1),
        expires_at=now + timedelta(days=1),
        created_at=now,
        last_seen_at=now,
    )

    class Session:
        async def get(self, _model, key):
            return stored if key == stored.session_token_hash else None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            dashboard_sessions.get_dashboard_session(
                _request("api.modral.app", cookie_value),
                Session(),
            )
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Dashboard session belongs to a different application"


def test_server_surface_mismatch_returns_canonical_dashboard(monkeypatch):
    async def dashboard_session(*_args, **_kwargs):
        return type("SessionProfile", (), {"application_profile": CYBERCOLORS_PROFILE})()

    class Session:
        async def get(self, model, key):
            assert model is Server
            return Server(server_id=key, server_name="Pilot", bot_profile=MODRAL_PROFILE)

    monkeypatch.setattr(server_access, "get_dashboard_session", dashboard_session)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            server_access.assert_server_surface(
                request=_request("cybercolors-api.modral.app"),
                session=Session(),
                server_id=987,
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "server_surface_mismatch"
    assert exc_info.value.detail["canonical_url"] == "https://dashboard.modral.app/dashboard/987"
