import sys
from types import SimpleNamespace

import pytest

from src.modules.ai.youtube_limits import youtube_duration_error
from src.modules.ai import knowledge_imports


@pytest.mark.parametrize("duration,expected", [(7200, None), (7199.9, None), (7200.1, "youtube_video_too_long"), (8518, "youtube_video_too_long"), (None, "youtube_duration_unknown"), (0, "youtube_duration_unknown"), (float("nan"), "youtube_duration_unknown")])
def test_duration_boundary(duration, expected):
    assert youtube_duration_error(duration) == expected


def test_oversized_video_rejected_before_audio_or_transcription(monkeypatch):
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs): return {"id": "fJHRrVlQYB4", "duration": 8518}
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=Downloader))
    monkeypatch.setattr(knowledge_imports, "youtube_runtime_diagnostics", lambda: {"yt_dlp_version":"test", "yt_dlp_ejs_version":"test", "deno_available":True, "deno_version":"test"})
    def forbidden(**kwargs): raise AssertionError("audio download/transcription must not start")
    monkeypatch.setattr(knowledge_imports, "_extract_youtube_audio_and_transcribe", forbidden)
    with pytest.raises(knowledge_imports.KnowledgeImportError) as error:
        knowledge_imports.extract_text_from_youtube_url("https://www.youtube.com/watch?v=fJHRrVlQYB4")
    assert error.value.code == "youtube_video_too_long"


@pytest.mark.parametrize("duration,code", [(7201, "youtube_video_too_long"), (None, "youtube_duration_unknown")])
def test_manual_channel_index_rejects_ineligible_video(monkeypatch, duration, code):
    import asyncio
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from api.services import youtube_channels
    monkeypatch.setattr(youtube_channels, "_get_subscription", AsyncMock(return_value=object()))
    monkeypatch.setattr(youtube_channels, "_get_channel_video", AsyncMock(return_value=SimpleNamespace(duration_seconds=duration)))
    with pytest.raises(HTTPException) as error:
        asyncio.run(youtube_channels.index_youtube_channel_video(object(), server_id=123, subscription_id="subscription", video_id="video", created_by_user_id=1))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == code
