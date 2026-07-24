import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_CHANNEL_PATH_PREFIXES = ("/@", "/channel/", "/c/", "/user/")
_VIDEO_PATH_PREFIXES = ("/shorts/", "/live/", "/embed/")


@dataclass(frozen=True, slots=True)
class YouTubeVideoUrl:
    video_id: str
    canonical_url: str


class YouTubeUrlError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_youtube_video_url(value: str) -> YouTubeVideoUrl:
    raw_url = value.strip()
    if not raw_url:
        raise YouTubeUrlError("youtube_url_missing", "A YouTube video URL is required.")

    candidate = raw_url if "://" in raw_url else f"https://{raw_url}"
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise YouTubeUrlError("youtube_url_invalid", "Enter a valid YouTube video URL.") from exc

    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = path.lstrip("/").split("/", 1)[0]
        return _normalized_video(video_id)

    if host not in _YOUTUBE_HOSTS:
        raise YouTubeUrlError("youtube_url_invalid", "Enter a valid YouTube video URL.")

    lowered_path = path.lower()
    if lowered_path.startswith(_CHANNEL_PATH_PREFIXES):
        raise YouTubeUrlError(
            "youtube_channel_url",
            "This is a YouTube channel link. Enter a link to an individual video.",
        )

    if lowered_path == "/playlist" or ("list" in query and "v" not in query):
        raise YouTubeUrlError(
            "youtube_playlist_url",
            "This is a YouTube playlist link. Enter a link to an individual video.",
        )

    if lowered_path == "/watch":
        return _normalized_video((query.get("v") or [""])[0])

    for prefix in _VIDEO_PATH_PREFIXES:
        if lowered_path.startswith(prefix):
            video_id = path[len(prefix) :].split("/", 1)[0]
            return _normalized_video(video_id)

    raise YouTubeUrlError("youtube_url_invalid", "Enter a valid YouTube video URL.")


def _normalized_video(video_id: str) -> YouTubeVideoUrl:
    if not _VIDEO_ID_PATTERN.fullmatch(video_id):
        raise YouTubeUrlError("youtube_url_invalid", "Enter a valid YouTube video URL.")
    return YouTubeVideoUrl(
        video_id=video_id,
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
    )
