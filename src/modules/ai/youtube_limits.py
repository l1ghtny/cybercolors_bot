"""Admission limits for knowledge-base YouTube imports."""
import math

MAX_YOUTUBE_DURATION_SECONDS = 2 * 60 * 60
YOUTUBE_DURATION_ERRORS = {
    "youtube_video_too_long": "YouTube videos must be no longer than 2 hours.",
    "youtube_duration_unknown": "The video duration could not be verified. Only videos up to 2 hours can be imported.",
}


def youtube_duration_error(duration: object) -> str | None:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return "youtube_duration_unknown"
    if duration > MAX_YOUTUBE_DURATION_SECONDS:
        return "youtube_video_too_long"
    return None
