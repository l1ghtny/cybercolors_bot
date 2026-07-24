"""Small, synchronous client for the public YouTube Data API v3.

The client deliberately keeps the API key at the HTTP boundary. It never adds
request URLs, response bodies, or provider error messages to exceptions or logs.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

import requests


logger = logging.getLogger(__name__)

_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_HANDLE_PATTERN = re.compile(r"^@[^\s/@?#]{3,30}$")
_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
}
_CHANNEL_TAB_PATHS = {"about", "community", "featured", "playlists", "shorts", "streams", "videos"}
_DEFAULT_TIMEOUT = (3.05, 15.0)
_MAX_TIMEOUT_SECONDS = 30.0
_PAGE_SIZE = 50


_SAFE_MESSAGES = {
    "youtube_data_not_configured": "YouTube channel synchronization is not configured.",
    "youtube_channel_url_invalid": "Enter a valid public YouTube channel URL or handle.",
    "youtube_channel_not_found": "This YouTube channel could not be found.",
    "youtube_data_auth_failed": "YouTube channel synchronization is not configured correctly.",
    "youtube_data_quota_exceeded": "YouTube channel synchronization is temporarily unavailable.",
    "youtube_data_rate_limited": "YouTube temporarily limited channel synchronization.",
    "youtube_data_unavailable": "YouTube channel information is temporarily unavailable.",
    "youtube_data_invalid_response": "YouTube returned an invalid channel response.",
    "youtube_data_request_failed": "YouTube channel information could not be retrieved.",
}


@dataclass(frozen=True, slots=True)
class YouTubeChannel:
    channel_id: str
    handle: str | None
    custom_url: str | None
    canonical_url: str
    title: str
    description: str
    thumbnail_url: str | None
    uploads_playlist_id: str


@dataclass(frozen=True, slots=True)
class YouTubeVideo:
    video_id: str
    channel_id: str
    canonical_url: str
    title: str
    description: str
    published_at: str | None
    duration_seconds: int | None
    thumbnail_url: str | None
    availability: str
    captions_available: bool | None


class YouTubeDataError(RuntimeError):
    """Provider failure whose string representation is safe to show to users."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(self.safe_message)


@dataclass(frozen=True, slots=True)
class _ChannelLookup:
    parameter: str
    value: str


class YouTubeDataClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = _DEFAULT_TIMEOUT,
    ) -> None:
        resolved_key = (
            api_key if api_key is not None else os.getenv("YOUTUBE_DATA_API_KEY", "")
        ).strip()
        if not resolved_key:
            raise YouTubeDataError("youtube_data_not_configured")
        self._api_key = resolved_key
        self._session = session or requests.Session()
        self._timeout = _validated_timeout(timeout)

    def resolve_channel(self, channel: str) -> YouTubeChannel:
        lookup = _parse_channel_lookup(channel)
        payload = self._request(
            "channels",
            {
                "part": "snippet,contentDetails",
                lookup.parameter: lookup.value,
                "maxResults": 1,
            },
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise YouTubeDataError("youtube_data_invalid_response")
        if not items:
            raise YouTubeDataError("youtube_channel_not_found")

        try:
            item = items[0]
            channel_id = _required_string(item, "id")
            snippet = _required_mapping(item, "snippet")
            content_details = _required_mapping(item, "contentDetails")
            related_playlists = _required_mapping(content_details, "relatedPlaylists")
            uploads_playlist_id = _required_string(related_playlists, "uploads")
            title = _required_string(snippet, "title")
        except (KeyError, TypeError, ValueError) as exc:
            raise YouTubeDataError("youtube_data_invalid_response") from exc

        custom_url = _optional_string(snippet.get("customUrl"))
        handle = _normalize_handle(custom_url)
        return YouTubeChannel(
            channel_id=channel_id,
            handle=handle,
            custom_url=custom_url,
            canonical_url=f"https://www.youtube.com/channel/{channel_id}",
            title=title,
            description=_optional_string(snippet.get("description")) or "",
            thumbnail_url=_best_thumbnail(snippet.get("thumbnails")),
            uploads_playlist_id=uploads_playlist_id,
        )

    def list_uploads(
        self,
        channel: YouTubeChannel,
        *,
        max_videos: int = 100,
    ) -> list[YouTubeVideo]:
        if isinstance(max_videos, bool) or not isinstance(max_videos, int) or max_videos < 0:
            raise ValueError("max_videos must be a non-negative integer")
        if max_videos == 0:
            return []

        playlist_items: list[dict[str, Any]] = []
        page_token: str | None = None
        while len(playlist_items) < max_videos:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": channel.uploads_playlist_id,
                "maxResults": min(_PAGE_SIZE, max_videos - len(playlist_items)),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._request("playlistItems", params)
            items = payload.get("items")
            if not isinstance(items, list):
                raise YouTubeDataError("youtube_data_invalid_response")
            playlist_items.extend(item for item in items if isinstance(item, dict))
            page_token = _optional_string(payload.get("nextPageToken"))
            if not page_token or not items:
                break

        playlist_items = playlist_items[:max_videos]
        video_ids = [_playlist_video_id(item) for item in playlist_items]
        video_ids = [video_id for video_id in video_ids if video_id]
        details_by_id: dict[str, Mapping[str, Any]] = {}
        for start in range(0, len(video_ids), _PAGE_SIZE):
            batch = video_ids[start : start + _PAGE_SIZE]
            payload = self._request(
                "videos",
                {
                    "part": "snippet,contentDetails,status",
                    "id": ",".join(batch),
                    "maxResults": len(batch),
                },
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise YouTubeDataError("youtube_data_invalid_response")
            for item in items:
                if isinstance(item, Mapping):
                    video_id = _optional_string(item.get("id"))
                    if video_id:
                        details_by_id[video_id] = item

        return [
            _normalize_video(item, channel.channel_id, details_by_id.get(video_id))
            for item, video_id in zip(playlist_items, [_playlist_video_id(item) for item in playlist_items])
            if video_id
        ]

    def _request(self, resource: str, params: Mapping[str, Any]) -> dict[str, Any]:
        started_at = time.monotonic()
        request_params = dict(params)
        request_params["key"] = self._api_key
        try:
            response = self._session.get(
                f"{_API_BASE_URL}/{resource}",
                params=request_params,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning(
                "youtube_data_request_failed",
                extra={
                    "youtube_api_resource": resource,
                    "youtube_api_exception_type": type(exc).__name__,
                },
            )
            raise YouTubeDataError("youtube_data_request_failed", retryable=True) from exc

        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        if response.status_code >= 400:
            code, retryable = _classify_http_error(response)
            logger.warning(
                "youtube_data_request_rejected",
                extra={
                    "youtube_api_resource": resource,
                    "youtube_api_status": response.status_code,
                    "youtube_api_error_code": code,
                    "youtube_api_elapsed_ms": elapsed_ms,
                },
            )
            raise YouTubeDataError(
                code,
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise YouTubeDataError("youtube_data_invalid_response") from exc
        if not isinstance(payload, dict):
            raise YouTubeDataError("youtube_data_invalid_response")

        item_count = len(payload.get("items", [])) if isinstance(payload.get("items"), list) else None
        logger.info(
            "youtube_data_request_succeeded",
            extra={
                "youtube_api_resource": resource,
                "youtube_api_status": response.status_code,
                "youtube_api_item_count": item_count,
                "youtube_api_elapsed_ms": elapsed_ms,
            },
        )
        return payload


def parse_youtube_duration_seconds(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value)
    if not match or not any(match.groupdict().values()):
        raise ValueError("Invalid ISO-8601 duration")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return int(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def _validated_timeout(timeout: tuple[float, float]) -> tuple[float, float]:
    if len(timeout) != 2:
        raise ValueError("timeout must contain connect and read seconds")
    connect_timeout, read_timeout = timeout
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < value <= _MAX_TIMEOUT_SECONDS
        for value in timeout
    ):
        raise ValueError(f"timeouts must be between 0 and {_MAX_TIMEOUT_SECONDS:g} seconds")
    return float(connect_timeout), float(read_timeout)


def _parse_channel_lookup(value: str) -> _ChannelLookup:
    raw_value = value.strip()
    if not raw_value:
        raise YouTubeDataError("youtube_channel_url_invalid")
    if _CHANNEL_ID_PATTERN.fullmatch(raw_value):
        return _ChannelLookup("id", raw_value)
    if _HANDLE_PATTERN.fullmatch(raw_value):
        return _ChannelLookup("forHandle", raw_value)

    candidate = raw_value if "://" in raw_value else f"https://{raw_value}"
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise YouTubeDataError("youtube_channel_url_invalid") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _YOUTUBE_HOSTS:
        raise YouTubeDataError("youtube_channel_url_invalid")

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) > 1 and parts[-1].lower() in _CHANNEL_TAB_PATHS:
        parts.pop()
    if len(parts) == 1 and _HANDLE_PATTERN.fullmatch(parts[0]):
        return _ChannelLookup("forHandle", parts[0])
    if len(parts) != 2:
        raise YouTubeDataError("youtube_channel_url_invalid")
    route, identifier = parts
    if route == "channel" and _CHANNEL_ID_PATTERN.fullmatch(identifier):
        return _ChannelLookup("id", identifier)
    if route == "user" and identifier:
        return _ChannelLookup("forUsername", identifier)
    if route == "c" and identifier:
        return _ChannelLookup("forHandle", identifier)
    raise YouTubeDataError("youtube_channel_url_invalid")


def _classify_http_error(response: requests.Response) -> tuple[str, bool]:
    reasons: set[str] = set()
    try:
        payload = response.json()
        errors = payload.get("error", {}).get("errors", [])
        reasons = {
            reason
            for error in errors
            if isinstance(error, Mapping)
            if (reason := _optional_string(error.get("reason")))
        }
    except (AttributeError, TypeError, ValueError, requests.JSONDecodeError):
        pass

    if reasons & {"quotaExceeded", "dailyLimitExceeded", "dailyLimitExceededUnreg"}:
        return "youtube_data_quota_exceeded", True
    if response.status_code == 429 or reasons & {"rateLimitExceeded", "userRateLimitExceeded"}:
        return "youtube_data_rate_limited", True
    if response.status_code in {401, 403}:
        return "youtube_data_auth_failed", False
    if response.status_code >= 500:
        return "youtube_data_unavailable", True
    return "youtube_data_request_failed", False


def _normalize_video(
    playlist_item: Mapping[str, Any],
    channel_id: str,
    details: Mapping[str, Any] | None,
) -> YouTubeVideo:
    video_id = _playlist_video_id(playlist_item)
    playlist_snippet = playlist_item.get("snippet")
    if not isinstance(playlist_snippet, Mapping):
        playlist_snippet = {}
    if details is None:
        return YouTubeVideo(
            video_id=video_id,
            channel_id=channel_id,
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            title=_optional_string(playlist_snippet.get("title")) or "",
            description=_optional_string(playlist_snippet.get("description")) or "",
            published_at=_optional_string(playlist_snippet.get("publishedAt")),
            duration_seconds=None,
            thumbnail_url=_best_thumbnail(playlist_snippet.get("thumbnails")),
            availability="unavailable",
            captions_available=None,
        )

    snippet = details.get("snippet")
    content_details = details.get("contentDetails")
    status = details.get("status")
    snippet = snippet if isinstance(snippet, Mapping) else {}
    content_details = content_details if isinstance(content_details, Mapping) else {}
    status = status if isinstance(status, Mapping) else {}
    duration = _optional_string(content_details.get("duration"))
    duration_seconds: int | None = None
    if duration:
        try:
            duration_seconds = parse_youtube_duration_seconds(duration)
        except ValueError:
            logger.warning(
                "youtube_data_invalid_video_duration",
                extra={"youtube_video_id": video_id},
            )

    captions_available = _parse_boolean_string(content_details.get("caption"))
    return YouTubeVideo(
        video_id=video_id,
        channel_id=_optional_string(snippet.get("channelId")) or channel_id,
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
        title=_optional_string(snippet.get("title")) or "",
        description=_optional_string(snippet.get("description")) or "",
        published_at=_optional_string(snippet.get("publishedAt")),
        duration_seconds=duration_seconds,
        thumbnail_url=_best_thumbnail(snippet.get("thumbnails")),
        availability=_video_availability(status),
        captions_available=captions_available,
    )


def _playlist_video_id(item: Mapping[str, Any]) -> str:
    content_details = item.get("contentDetails")
    if isinstance(content_details, Mapping):
        video_id = _optional_string(content_details.get("videoId"))
        if video_id:
            return video_id
    snippet = item.get("snippet")
    if isinstance(snippet, Mapping):
        resource_id = snippet.get("resourceId")
        if isinstance(resource_id, Mapping):
            return _optional_string(resource_id.get("videoId")) or ""
    return ""


def _video_availability(status: Mapping[str, Any]) -> str:
    upload_status = _optional_string(status.get("uploadStatus"))
    if upload_status and upload_status != "processed":
        return upload_status
    privacy_status = _optional_string(status.get("privacyStatus"))
    if privacy_status and privacy_status != "public":
        return privacy_status
    return "available"


def _parse_boolean_string(value: object) -> bool | None:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    return None


def _normalize_handle(custom_url: str | None) -> str | None:
    if not custom_url:
        return None
    candidate = custom_url if custom_url.startswith("@") else f"@{custom_url}"
    return candidate if _HANDLE_PATTERN.fullmatch(candidate) else None


def _best_thumbnail(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for quality in ("maxres", "standard", "high", "medium", "default"):
        thumbnail = value.get(quality)
        if isinstance(thumbnail, Mapping):
            url = _optional_string(thumbnail.get("url"))
            if url:
                return url
    return None


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value[key]
    if not isinstance(nested, Mapping):
        raise TypeError(f"{key} is not an object")
    return nested


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = _optional_string(value[key])
    if not result:
        raise ValueError(f"{key} is missing")
    return result


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
