PUBLIC_KNOWLEDGE_ERRORS = {
    "empty_file": "The uploaded file is empty.",
    "file_too_large": "The uploaded file is too large.",
    "file_not_found": "The uploaded file could not be found.",
    "invalid_storage_key": "The uploaded file could not be read.",
    "unsupported_file_type": "This file type is not supported.",
    "empty_extraction": "No readable content was found in this source.",
    "empty_source": "No indexable content was found in this source.",
    "youtube_url_missing": "A YouTube video URL is required.",
    "youtube_url_invalid": "Enter a valid YouTube video URL.",
    "youtube_channel_url": "This is a YouTube channel link. Enter a link to an individual video.",
    "youtube_playlist_url": "This is a YouTube playlist link. Enter a link to an individual video.",
    "youtube_access_challenge": "YouTube temporarily rejected the request. Please try again later.",
    "youtube_unavailable": "This YouTube video is unavailable or cannot be accessed.",
    "youtube_fetch_failed": "YouTube could not be reached while reading this video.",
    "youtube_captions_missing": "No captions were available for this YouTube video.",
    "youtube_audio_download_failed": "The video's audio could not be retrieved from YouTube.",
    "youtube_audio_missing": "No usable audio was found for this YouTube video.",
    "empty_transcription": "The video was processed, but no transcript was produced.",
    "modal_transcription_not_configured": "Video transcription is not currently available.",
    "modal_transcription_failed": "The video transcription service could not process this video.",
    "modal_token_invalid": "The video transcription service is temporarily unavailable.",
    "modal_transcription_invalid_response": "The video transcription service returned an invalid response.",
    "modal_missing": "Video transcription is not currently available.",
    "yt_dlp_missing": "YouTube importing is not currently available.",
}


def public_knowledge_error(error_code: str | None, raw_error: str | None) -> str | None:
    if not raw_error:
        return None
    return PUBLIC_KNOWLEDGE_ERRORS.get(error_code or "", "This knowledge source could not be indexed.")
