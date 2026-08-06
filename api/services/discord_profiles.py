import inspect
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status


CYBERCOLORS_PROFILE = "cybercolors"
MODRAL_PROFILE = "modral"
SUPPORTED_PROFILES = frozenset({CYBERCOLORS_PROFILE, MODRAL_PROFILE})
_server_profile_cache: dict[int, str] = {}


async def call_with_server_profile(
    function: Callable[..., Awaitable[Any]],
    *args: Any,
    server_id: int | None,
    **kwargs: Any,
) -> Any:
    """Pass server routing to profile-aware callables while supporting legacy adapters."""
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    supports_server_id = any(
        parameter.name == "server_id" or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if supports_server_id and server_id is not None:
        kwargs["server_id"] = server_id
    return await function(*args, **kwargs)


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _csv_env(name: str, defaults: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return defaults
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class DiscordApplicationProfile:
    key: str
    display_name: str
    frontend_origin: str
    api_hosts: tuple[str, ...]
    redirect_uris: tuple[str, ...]
    client_id: str | None
    client_secret: str | None
    bot_token: str | None
    dashboard_base_url: str

    @property
    def application_id(self) -> str | None:
        return self.client_id


def get_profile(profile_key: str) -> DiscordApplicationProfile:
    key = profile_key.strip().lower()
    if key == MODRAL_PROFILE:
        frontend_origin = (
            os.getenv("MODRAL_DASHBOARD_ORIGIN")
            or os.getenv("DASHBOARD_BASE_URL")
            or "https://dashboard.modral.app"
        ).rstrip("/")
        return DiscordApplicationProfile(
            key=key,
            display_name="Modral",
            frontend_origin=frontend_origin,
            api_hosts=_csv_env("MODRAL_API_HOSTS", ("api.modral.app",)),
            redirect_uris=_csv_env(
                "MODRAL_DASHBOARD_OAUTH_REDIRECT_URIS",
                (f"{frontend_origin}/callback",),
            ),
            client_id=_env_first("MODRAL_DISCORD_CLIENT_ID"),
            client_secret=_env_first("MODRAL_DISCORD_CLIENT_SECRET"),
            bot_token=_env_first("MODRAL_DISCORD_BOT_TOKEN"),
            dashboard_base_url=frontend_origin,
        )
    if key == CYBERCOLORS_PROFILE:
        frontend_origin = os.getenv(
            "CYBERCOLORS_DASHBOARD_ORIGIN", "https://cybercolors.modral.app"
        ).rstrip("/")
        return DiscordApplicationProfile(
            key=key,
            display_name="CyberColors",
            frontend_origin=frontend_origin,
            api_hosts=_csv_env(
                "CYBERCOLORS_API_HOSTS",
                ("cybercolors-api.modral.app", "cybercolors-api.lightny.pro"),
            ),
            redirect_uris=_csv_env(
                "CYBERCOLORS_DASHBOARD_OAUTH_REDIRECT_URIS",
                (f"{frontend_origin}/callback",),
            ),
            client_id=_env_first("CYBERCOLORS_DISCORD_CLIENT_ID", "DISCORD_CLIENT_ID"),
            client_secret=_env_first(
                "CYBERCOLORS_DISCORD_CLIENT_SECRET", "DISCORD_CLIENT_SECRET"
            ),
            bot_token=_env_first(
                "CYBERCOLORS_DISCORD_BOT_TOKEN",
                "DISCORD_BOT_TOKEN",
                "DISCORD_TOKEN_TEST",
                "DISCORD_TOKEN",
            ),
            dashboard_base_url=frontend_origin,
        )
    raise ValueError(f"Unsupported Discord application profile: {profile_key}")


def default_profile_key() -> str:
    value = os.getenv("DASHBOARD_DEFAULT_PROFILE", CYBERCOLORS_PROFILE).strip().lower()
    return value if value in SUPPORTED_PROFILES else CYBERCOLORS_PROFILE


def runtime_bot_profile_key() -> str:
    value = os.getenv("BOT_PROFILE", CYBERCOLORS_PROFILE).strip().lower()
    if value not in SUPPORTED_PROFILES:
        raise RuntimeError(f"BOT_PROFILE must be one of: {', '.join(sorted(SUPPORTED_PROFILES))}")
    return value


def profile_for_api_host(host: str) -> DiscordApplicationProfile:
    normalized = host.split(":", 1)[0].strip().lower()
    for profile_key in (MODRAL_PROFILE, CYBERCOLORS_PROFILE):
        profile = get_profile(profile_key)
        if normalized in {item.lower() for item in profile.api_hosts}:
            return profile
    if normalized in {"localhost", "127.0.0.1", "testserver"}:
        return get_profile(default_profile_key())
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unknown dashboard API host",
    )


def profile_for_request(request: Request) -> DiscordApplicationProfile:
    return profile_for_api_host(request.url.hostname or request.headers.get("host", ""))


def validate_profile_redirect_uri(
    profile: DiscordApplicationProfile,
    redirect_uri: str | None,
) -> str:
    resolved = (redirect_uri or (profile.redirect_uris[0] if profile.redirect_uris else "")).strip()
    allowed = set(profile.redirect_uris)
    if os.getenv("DASHBOARD_ALLOW_LOCAL_OAUTH_REDIRECTS", "false").lower() == "true":
        allowed.update(
            {
                "http://127.0.0.1:5173/callback",
                "http://localhost:5173/callback",
                "http://127.0.0.1:8080/callback",
                "http://localhost:8080/callback",
            }
        )
    if not resolved or resolved not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth redirect URI is not allowed for this dashboard",
        )
    return resolved


def cybercolors_guild_ids() -> frozenset[int]:
    configured = {
        int(value)
        for value in _csv_env("CYBERCOLORS_GUILD_IDS")
        if value.isdigit()
    }
    legacy = (os.getenv("TEST_GUILD_ID") or "").strip()
    if legacy.isdigit():
        configured.add(int(legacy))
    return frozenset(configured)


def cache_server_profile(server_id: int, profile_key: str) -> None:
    """Cache the persisted primary gateway for synchronous Discord helpers."""
    normalized = profile_key.strip().lower()
    if normalized not in SUPPORTED_PROFILES:
        raise ValueError(f"Unsupported Discord application profile: {profile_key}")
    _server_profile_cache[int(server_id)] = normalized


def clear_server_profile_cache() -> None:
    _server_profile_cache.clear()


def profile_key_for_server_id(server_id: int) -> str:
    cached = _server_profile_cache.get(int(server_id))
    if cached is not None:
        return cached
    return CYBERCOLORS_PROFILE if int(server_id) in cybercolors_guild_ids() else MODRAL_PROFILE


def dashboard_base_url_for_server(server_id: int) -> str:
    return get_profile(profile_key_for_server_id(server_id)).dashboard_base_url


def invite_url_for_profile(profile: DiscordApplicationProfile, *, guild_id: int | None = None) -> str:
    if not profile.client_id:
        raise HTTPException(status_code=503, detail="Discord application is not configured")
    query = (
        f"client_id={profile.client_id}&scope=bot%20applications.commands"
        "&permissions=8&integration_type=0"
    )
    if guild_id is not None:
        query += f"&guild_id={int(guild_id)}&disable_guild_select=true"
    return f"https://discord.com/oauth2/authorize?{query}"


def frontend_profile_for_origin(origin: str) -> DiscordApplicationProfile | None:
    normalized = origin.rstrip("/").lower()
    for profile_key in (MODRAL_PROFILE, CYBERCOLORS_PROFILE):
        profile = get_profile(profile_key)
        if profile.frontend_origin.lower() == normalized:
            return profile
    parsed = urlparse(normalized)
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        return get_profile(default_profile_key())
    return None
