import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import HTTPException, Request, Response, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.models import DashboardSession

DISCORD_API_BASE_URL = "https://discord.com/api/v10"
SESSION_COOKIE_NAME = os.getenv("DASHBOARD_SESSION_COOKIE_NAME", "cybercolors_session")
OAUTH_STATE_COOKIE_NAME = os.getenv("DASHBOARD_OAUTH_STATE_COOKIE_NAME", "cybercolors_oauth_state")
SESSION_TTL_SECONDS = int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", str(7 * 24 * 60 * 60)))
SESSION_COOKIE_SECURE = os.getenv("DASHBOARD_SESSION_COOKIE_SECURE", "true").lower() == "true"
SESSION_COOKIE_DOMAIN = os.getenv("DASHBOARD_SESSION_COOKIE_DOMAIN") or None
SESSION_COOKIE_SAMESITE = os.getenv("DASHBOARD_SESSION_COOKIE_SAMESITE", "lax").lower()
OAUTH_STATE_TTL_SECONDS = int(os.getenv("DASHBOARD_OAUTH_STATE_TTL_SECONDS", "600"))
SESSION_TOUCH_INTERVAL_SECONDS = int(os.getenv("DASHBOARD_SESSION_TOUCH_INTERVAL_SECONDS", "900"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_cipher() -> MultiFernet:
    configured_keys = [
        item.strip()
        for item in os.getenv("DASHBOARD_SESSION_ENCRYPTION_KEYS", "").split(",")
        if item.strip()
    ]
    if not configured_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard session encryption is not configured",
        )
    try:
        return MultiFernet([Fernet(key.encode("ascii")) for key in configured_keys])
    except (ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard session encryption is misconfigured",
        ) from exc


def _encrypt_token(token: str | None) -> str | None:
    if token is None:
        return None
    return _session_cipher().encrypt(token.encode("utf-8")).decode("ascii")


def _decrypt_token(token: str | None) -> str | None:
    if token is None:
        return None
    try:
        return _session_cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dashboard session is invalid",
        ) from exc


def _cookie_options() -> dict[str, object]:
    return {
        "httponly": True,
        "secure": SESSION_COOKIE_SECURE,
        "samesite": SESSION_COOKIE_SAMESITE,
        "domain": SESSION_COOKIE_DOMAIN,
        "path": "/",
    }


def allowed_redirect_uris() -> set[str]:
    configured = {
        item.strip()
        for item in os.getenv("DASHBOARD_OAUTH_REDIRECT_URIS", "").split(",")
        if item.strip()
    }
    default_redirect = os.getenv("DISCORD_REDIRECT_URI")
    if default_redirect:
        configured.add(default_redirect.strip())
    if os.getenv("DASHBOARD_ALLOW_LOCAL_OAUTH_REDIRECTS", "false").lower() == "true":
        configured.update(
            {
                "http://127.0.0.1:5173/callback",
                "http://localhost:5173/callback",
                "http://127.0.0.1:8080/callback",
                "http://localhost:8080/callback",
            }
        )
    return configured


def validate_redirect_uri(redirect_uri: str | None) -> str:
    resolved = (redirect_uri or os.getenv("DISCORD_REDIRECT_URI") or "").strip()
    if not resolved or resolved not in allowed_redirect_uris():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth redirect URI is not allowed")
    return resolved


def build_discord_authorize_url(
    response: Response,
    *,
    redirect_uri: str,
    command_management: bool,
) -> tuple[str, str]:
    client_id = os.getenv("DISCORD_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="Discord client ID is not configured")

    state_token = secrets.token_urlsafe(32)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        state_token,
        max_age=OAUTH_STATE_TTL_SECONDS,
        **_cookie_options(),
    )
    scope = "identify guilds"
    if command_management:
        scope += " applications.commands.permissions.update"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state_token,
    }
    if command_management:
        params["prompt"] = "consent"
    return f"https://discord.com/api/oauth2/authorize?{urlencode(params)}", state_token


def validate_oauth_state(request: Request, response: Response, state_token: str | None) -> None:
    expected = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, **_cookie_options())
    if not expected or not state_token or not secrets.compare_digest(expected, state_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state did not match")


async def create_dashboard_session(
    session: AsyncSession,
    response: Response,
    *,
    discord_user_id: int,
    token_payload: dict,
) -> None:
    now = _utcnow()
    session_token = secrets.token_urlsafe(32)
    access_expires_at = now + timedelta(seconds=max(1, int(token_payload.get("expires_in", 3600))))
    session_expires_at = now + timedelta(seconds=SESSION_TTL_SECONDS)
    session.add(
        DashboardSession(
            session_token_hash=_token_hash(session_token),
            discord_user_id=discord_user_id,
            discord_access_token=_encrypt_token(str(token_payload["access_token"])),
            discord_refresh_token=_encrypt_token(token_payload.get("refresh_token")),
            discord_token_expires_at=access_expires_at,
            expires_at=session_expires_at,
            created_at=now,
            last_seen_at=now,
        )
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=SESSION_TTL_SECONDS,
        **_cookie_options(),
    )


async def _refresh_discord_access_token(
    db_session: AsyncSession,
    dashboard_session: DashboardSession,
) -> str:
    client_id = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    refresh_token = _decrypt_token(dashboard_session.discord_refresh_token)
    if not client_id or not client_secret or not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard session expired")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{DISCORD_API_BASE_URL}/oauth2/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        await db_session.delete(dashboard_session)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard session expired")

    payload = response.json()
    now = _utcnow()
    access_token = str(payload["access_token"])
    dashboard_session.discord_access_token = _encrypt_token(access_token)
    dashboard_session.discord_refresh_token = _encrypt_token(payload.get("refresh_token", refresh_token))
    dashboard_session.discord_token_expires_at = now + timedelta(
        seconds=max(1, int(payload.get("expires_in", 3600)))
    )
    dashboard_session.last_seen_at = now
    db_session.add(dashboard_session)
    return access_token


async def get_dashboard_session(
    request: Request,
    db_session: AsyncSession,
    *,
    required: bool = True,
) -> DashboardSession | None:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard session missing")
        return None

    dashboard_session = await db_session.get(DashboardSession, _token_hash(session_token))
    now = _utcnow()
    if dashboard_session is None or dashboard_session.expires_at <= now:
        if dashboard_session is not None:
            await db_session.delete(dashboard_session)
        if required:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dashboard session expired")
        return None

    if dashboard_session.discord_token_expires_at <= now + timedelta(seconds=30):
        await _refresh_discord_access_token(db_session, dashboard_session)
    elif dashboard_session.last_seen_at <= now - timedelta(seconds=SESSION_TOUCH_INTERVAL_SECONDS):
        dashboard_session.last_seen_at = now
        db_session.add(dashboard_session)
    return dashboard_session


async def get_dashboard_discord_access_token(
    request: Request,
    db_session: AsyncSession,
    *,
    required: bool = True,
) -> str | None:
    dashboard_session = await get_dashboard_session(request, db_session, required=required)
    return _decrypt_token(dashboard_session.discord_access_token) if dashboard_session else None


async def revoke_dashboard_session(request: Request, response: Response, db_session: AsyncSession) -> None:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        dashboard_session = await db_session.get(DashboardSession, _token_hash(session_token))
        if dashboard_session is not None:
            await db_session.delete(dashboard_session)
    response.delete_cookie(SESSION_COOKIE_NAME, **_cookie_options())
