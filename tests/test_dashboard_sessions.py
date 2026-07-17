import asyncio
import importlib
from http.cookies import SimpleCookie

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Response

from api.models.auth import AuthLoginRequestModel, AuthLoginResponseModel, AuthUserModel
from api.services import dashboard_sessions

auth_router = importlib.import_module("api.routers.auth")


class FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.records = {}

    def add(self, value):
        self.added.append(value)
        self.records[value.session_token_hash] = value

    async def get(self, _model, key):
        return self.records.get(key)

    async def delete(self, value):
        self.deleted.append(value)
        self.records.pop(value.session_token_hash, None)


def _request_with_cookie(name: str, value: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", f"{name}={value}".encode("ascii"))],
        }
    )


def test_dashboard_session_uses_opaque_cookie_and_encrypted_discord_tokens(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SESSION_ENCRYPTION_KEYS", Fernet.generate_key().decode("ascii"))
    monkeypatch.setattr(dashboard_sessions, "SESSION_COOKIE_SECURE", True)
    fake_session = FakeSession()
    response = Response()

    asyncio.run(
        dashboard_sessions.create_dashboard_session(
            fake_session,
            response,
            discord_user_id=123,
            token_payload={
                "access_token": "discord-access-token",
                "refresh_token": "discord-refresh-token",
                "expires_in": 3600,
            },
        )
    )

    assert len(fake_session.added) == 1
    stored = fake_session.added[0]
    assert stored.discord_access_token != "discord-access-token"
    assert stored.discord_refresh_token != "discord-refresh-token"
    assert dashboard_sessions._decrypt_token(stored.discord_access_token) == "discord-access-token"
    assert dashboard_sessions._decrypt_token(stored.discord_refresh_token) == "discord-refresh-token"

    cookie_header = response.headers["set-cookie"]
    parsed = SimpleCookie()
    parsed.load(cookie_header)
    browser_token = parsed[dashboard_sessions.SESSION_COOKIE_NAME].value
    assert browser_token not in {"discord-access-token", "discord-refresh-token"}
    assert stored.session_token_hash == dashboard_sessions._token_hash(browser_token)
    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()


def test_dashboard_session_encryption_is_required(monkeypatch):
    monkeypatch.delenv("DASHBOARD_SESSION_ENCRYPTION_KEYS", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        dashboard_sessions._encrypt_token("sensitive")

    assert exc_info.value.status_code == 503


def test_oauth_state_is_server_generated_and_validated(monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "123456")
    monkeypatch.setattr(dashboard_sessions, "SESSION_COOKIE_SECURE", True)
    response = Response()

    authorize_url, state_token = dashboard_sessions.build_discord_authorize_url(
        response,
        redirect_uri="https://cybercolors.modral.app/callback",
        command_management=False,
    )

    assert "client_id=123456" in authorize_url
    assert f"state={state_token}" in authorize_url
    validation_response = Response()
    dashboard_sessions.validate_oauth_state(
        _request_with_cookie(dashboard_sessions.OAUTH_STATE_COOKIE_NAME, state_token),
        validation_response,
        state_token,
    )
    assert "max-age=0" in validation_response.headers["set-cookie"].lower()


def test_login_response_cannot_serialize_discord_tokens():
    response = AuthLoginResponseModel(
        message="Login successful",
        user=AuthUserModel(discord_id="123", username="tester", avatar_hash=None),
    )

    payload = response.model_dump()
    assert payload == {
        "message": "Login successful",
        "user": {"discord_id": "123", "username": "tester", "avatar_hash": None},
    }
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_login_commits_dashboard_session_before_returning(monkeypatch):
    events: list[str] = []

    class StubHttpResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class StubHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return StubHttpResponse(
                {
                    "access_token": "discord-access-token",
                    "refresh_token": "discord-refresh-token",
                    "expires_in": 3600,
                }
            )

        async def get(self, *_args, **_kwargs):
            return StubHttpResponse({"id": "123", "username": "tester", "avatar": None})

    class LoginSession:
        async def get(self, _model, _key):
            return None

        def add(self, _value):
            return None

        async def flush(self):
            events.append("flush")

        async def commit(self):
            events.append("commit")

    async def create_session(*_args, **_kwargs):
        events.append("create_session")

    monkeypatch.setattr(auth_router, "DISCORD_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth_router, "DISCORD_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(auth_router, "validate_oauth_state", lambda *_args: None)
    monkeypatch.setattr(
        auth_router,
        "validate_redirect_uri",
        lambda _redirect_uri: "https://cybercolors.modral.app/callback",
    )
    monkeypatch.setattr(auth_router.httpx, "AsyncClient", lambda **_kwargs: StubHttpClient())
    monkeypatch.setattr(auth_router, "create_dashboard_session", create_session)

    result = asyncio.run(
        auth_router.login(
            AuthLoginRequestModel(
                code="oauth-code",
                state="oauth-state",
                redirect_uri="https://cybercolors.modral.app/callback",
            ),
            _request_with_cookie(dashboard_sessions.OAUTH_STATE_COOKIE_NAME, "oauth-state"),
            Response(),
            LoginSession(),
        )
    )

    assert result.message == "Login successful"
    assert events == ["flush", "create_session", "commit"]


def test_local_redirects_are_disabled_unless_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("DASHBOARD_OAUTH_REDIRECT_URIS", "https://cybercolors.modral.app/callback")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://cybercolors.modral.app/callback")
    monkeypatch.delenv("DASHBOARD_ALLOW_LOCAL_OAUTH_REDIRECTS", raising=False)

    assert dashboard_sessions.validate_redirect_uri(None) == "https://cybercolors.modral.app/callback"
    with pytest.raises(HTTPException) as exc_info:
        dashboard_sessions.validate_redirect_uri("http://127.0.0.1:5173/callback")
    assert exc_info.value.status_code == 400

    monkeypatch.setenv("DASHBOARD_ALLOW_LOCAL_OAUTH_REDIRECTS", "true")
    assert (
        dashboard_sessions.validate_redirect_uri("http://127.0.0.1:5173/callback")
        == "http://127.0.0.1:5173/callback"
    )
