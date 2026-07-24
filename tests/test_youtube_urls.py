import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.models.ai_knowledge import AIKnowledgeSourceCreateModel
from src.modules.ai.knowledge_errors import public_knowledge_error
from src.modules.ai.knowledge_imports import KnowledgeImportError, extract_text_from_youtube_url
from src.modules.ai.youtube_urls import YouTubeUrlError, normalize_youtube_video_url


@pytest.mark.parametrize(
    ("url", "video_id"),
    [
        ("https://www.youtube.com/watch?v=abc123DEF_0", "abc123DEF_0"),
        ("https://youtu.be/abc123DEF_0?t=30", "abc123DEF_0"),
        ("https://www.youtube.com/shorts/abc123DEF_0", "abc123DEF_0"),
        ("youtube.com/live/abc123DEF_0", "abc123DEF_0"),
        ("https://www.youtube.com/watch?v=abc123DEF_0&list=PL123", "abc123DEF_0"),
    ],
)
def test_normalize_youtube_video_url(url: str, video_id: str):
    normalized = normalize_youtube_video_url(url)

    assert normalized.video_id == video_id
    assert normalized.canonical_url == f"https://www.youtube.com/watch?v={video_id}"


@pytest.mark.parametrize(
    ("url", "error_code"),
    [
        ("https://www.youtube.com/@StudioColors", "youtube_channel_url"),
        ("https://www.youtube.com/channel/UCabc123", "youtube_channel_url"),
        ("https://www.youtube.com/playlist?list=PL123", "youtube_playlist_url"),
        ("https://example.com/watch?v=abc123DEF_0", "youtube_url_invalid"),
        ("https://www.youtube.com/watch?v=short", "youtube_url_invalid"),
    ],
)
def test_rejects_non_video_youtube_urls(url: str, error_code: str):
    with pytest.raises(YouTubeUrlError) as caught:
        normalize_youtube_video_url(url)

    assert caught.value.code == error_code


def test_youtube_source_create_model_canonicalizes_video_url():
    model = AIKnowledgeSourceCreateModel(
        source_type="youtube",
        title="Video",
        source_url="https://youtu.be/abc123DEF_0?si=tracking",
    )

    assert model.source_url == "https://www.youtube.com/watch?v=abc123DEF_0"


def test_youtube_source_create_model_rejects_channel_url():
    with pytest.raises(ValidationError, match="YouTube channel link") as caught:
        AIKnowledgeSourceCreateModel(
            source_type="youtube",
            title="Channel",
            source_url="https://www.youtube.com/@StudioColors",
        )

    assert caught.value.errors()[0]["type"] == "youtube_channel_url"


def test_extractor_rejects_channel_before_calling_ytdlp():
    with pytest.raises(KnowledgeImportError) as caught:
        extract_text_from_youtube_url("https://www.youtube.com/@StudioColors")

    assert caught.value.code == "youtube_channel_url"


def test_extractor_canonicalizes_video_and_disables_playlist(monkeypatch):
    calls: dict[str, object] = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            calls["options"] = options
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, url, *, download):
            calls["url"] = url
            calls["download"] = download
            caption_path = Path(
                self.options["outtmpl"]
                .replace("%(id)s", "abc123DEF_0")
                .replace("%(ext)s", "en.vtt")
            )
            caption_path.write_text("WEBVTT\n\n00:00.000 --> 00:02.000\nHello from captions", encoding="utf-8")
            return {
                "id": "abc123DEF_0",
                "title": "Test video",
                "duration": 2,
                "webpage_url": "https://www.youtube.com/watch?v=abc123DEF_0",
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(
        "src.modules.ai.knowledge_imports.youtube_runtime_diagnostics",
        lambda: {"yt_dlp_version": "test", "yt_dlp_ejs_version": "test", "deno_available": True},
    )

    text, metadata = extract_text_from_youtube_url(
        "https://www.youtube.com/watch?v=abc123DEF_0&list=PLignored"
    )

    assert text == "Hello from captions"
    assert metadata["video_id"] == "abc123DEF_0"
    assert calls["url"] == "https://www.youtube.com/watch?v=abc123DEF_0"
    assert calls["download"] is True
    assert calls["options"]["noplaylist"] is True


def test_extractor_classifies_access_challenge_without_exposing_raw_error(monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, *_args, **_kwargs):
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies-from-browser secret-profile")

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(
        "src.modules.ai.knowledge_imports.youtube_runtime_diagnostics",
        lambda: {"yt_dlp_version": "test", "yt_dlp_ejs_version": "test", "deno_available": True},
    )

    with pytest.raises(KnowledgeImportError) as caught:
        extract_text_from_youtube_url("https://www.youtube.com/watch?v=abc123DEF_0")

    assert caught.value.code == "youtube_access_challenge"
    assert "cookies" not in str(caught.value).lower()


def test_public_error_never_returns_raw_extractor_message():
    raw_error = "ERROR: [youtube] secret details and --cookies-from-browser"

    assert public_knowledge_error("youtube_access_challenge", raw_error) == (
        "YouTube temporarily rejected the request. Please try again later."
    )
    assert public_knowledge_error("unknown_internal_error", raw_error) == (
        "This knowledge source could not be indexed."
    )
