PUBLIC_YOUTUBE_CHANNEL_ERRORS = {
    "youtube_data_not_configured": "YouTube channel synchronization is not configured.",
    "youtube_channel_url_invalid": "Enter a valid YouTube channel URL or handle.",
    "youtube_channel_not_found": "This YouTube channel could not be found.",
    "youtube_data_quota_exceeded": "YouTube channel synchronization is temporarily unavailable.",
    "youtube_data_rate_limited": "YouTube temporarily limited channel synchronization.",
    "youtube_data_auth_failed": "YouTube channel synchronization is not configured correctly.",
    "youtube_data_unavailable": "YouTube channel information is temporarily unavailable.",
    "youtube_data_request_failed": "YouTube could not be reached while synchronizing this channel.",
    "youtube_data_invalid_response": "YouTube returned an invalid channel response.",
}


def public_youtube_channel_error(error_code: str | None, raw_error: str | None) -> str | None:
    if not raw_error:
        return None
    return PUBLIC_YOUTUBE_CHANNEL_ERRORS.get(
        error_code or "",
        "This YouTube channel could not be synchronized.",
    )
