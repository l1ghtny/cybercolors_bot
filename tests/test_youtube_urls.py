import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.models.ai_knowledge import AIKnowledgeSourceCreateModel
from src.modules.ai.knowledge_errors import public_knowledge_error
from src.modules.ai.knowledge_imports import (
    KnowledgeImportError,
    _download_youtube_audio,
    _redact_url_credentials,
    extract_text_from_youtube_url,
    youtube_runtime_diagnostics,
)
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


def test_youtube_runtime_diagnostics_executes_deno(monkeypatch):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="deno 2.8.1\nv8 test\ntypescript test\n")

    youtube_runtime_diagnostics.cache_clear()
    monkeypatch.setattr("src.modules.ai.knowledge_imports.shutil.which", lambda _name: "/usr/local/bin/deno")
    monkeypatch.setattr("src.modules.ai.knowledge_imports.subprocess.run", fake_run)
    try:
        diagnostics = youtube_runtime_diagnostics()
    finally:
        youtube_runtime_diagnostics.cache_clear()

    assert diagnostics["deno_available"] is True
    assert diagnostics["deno_version"] == "2.8.1"
    assert calls == [
        (
            ["/usr/local/bin/deno", "--version"],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 5,
            },
        )
    ]


def test_youtube_runtime_diagnostics_rejects_unusable_deno(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise OSError("missing dynamic linker")

    youtube_runtime_diagnostics.cache_clear()
    monkeypatch.setattr("src.modules.ai.knowledge_imports.shutil.which", lambda _name: "/usr/local/bin/deno")
    monkeypatch.setattr("src.modules.ai.knowledge_imports.subprocess.run", fake_run)
    try:
        diagnostics = youtube_runtime_diagnostics()
    finally:
        youtube_runtime_diagnostics.cache_clear()

    assert diagnostics["deno_available"] is False
    assert diagnostics["deno_version"] is None


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
        lambda: {
            "yt_dlp_version": "test",
            "yt_dlp_ejs_version": "test",
            "deno_available": True,
            "deno_version": "test",
        },
    )

    text, metadata = extract_text_from_youtube_url(
        "https://www.youtube.com/watch?v=abc123DEF_0&list=PLignored"
    )

    assert text == "Hello from captions"
    assert metadata["video_id"] == "abc123DEF_0"
    assert calls["url"] == "https://www.youtube.com/watch?v=abc123DEF_0"
    assert calls["download"] is True
    assert calls["options"]["noplaylist"] is True
    assert calls["options"]["writesubtitles"] is True
    assert calls["options"]["writeautomaticsub"] is False


def test_extractor_uses_configured_proxy_without_logging_credentials(monkeypatch, caplog):
    calls: dict[str, object] = {}
    caplog.set_level(logging.INFO)

    class FakeYoutubeDL:
        def __init__(self, options):
            calls["options"] = options
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, *, download):
            assert download is True
            caption_path = Path(
                self.options["outtmpl"]
                .replace("%(id)s", "abc123DEF_0")
                .replace("%(ext)s", "en.vtt")
            )
            caption_path.write_text("WEBVTT\n\n00:00.000 --> 00:02.000\nHello", encoding="utf-8")
            return {"id": "abc123DEF_0", "title": "Test", "duration": 2}

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    proxy_url = "http://proxy-user:proxy-secret@proxy.example:8080"
    monkeypatch.setattr("src.modules.ai.knowledge_imports.YOUTUBE_PROXY_URL", proxy_url)
    monkeypatch.setattr(
        "src.modules.ai.knowledge_imports.youtube_runtime_diagnostics",
        lambda: {
            "yt_dlp_version": "test",
            "yt_dlp_ejs_version": "test",
            "deno_available": True,
            "deno_version": "test",
        },
    )

    text, _metadata = extract_text_from_youtube_url(
        "https://www.youtube.com/watch?v=abc123DEF_0"
    )

    assert text == "Hello"
    assert calls["options"]["proxy"] == proxy_url
    assert "youtube_proxy_enabled" in caplog.text
    assert "proxy-secret" not in caplog.text


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
        lambda: {
            "yt_dlp_version": "test",
            "yt_dlp_ejs_version": "test",
            "deno_available": True,
            "deno_version": "test",
        },
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
    assert public_knowledge_error("youtube_audio_too_large", raw_error) == (
        "The video's audio is too large to transcribe."
    )


def test_proxy_credentials_are_redacted_from_ytdlp_diagnostics():
    assert _redact_url_credentials(
        "Proxy failed: socks5h://user:super-secret@proxy.example:1080/path"
    ) == "Proxy failed: socks5h://***@proxy.example:1080/path"


def test_audio_download_uses_proxy_and_bandwidth_efficient_options(monkeypatch, tmp_path):
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
            audio_path = Path(
                self.options["outtmpl"]
                .replace("%(id)s", "abc123DEF_0")
                .replace("%(ext)s", "m4a")
            )
            audio_path.write_bytes(b"audio")
            return {"id": "abc123DEF_0"}

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(
        "src.modules.ai.knowledge_imports.YOUTUBE_PROXY_URL",
        "http://proxy-user:proxy-secret@proxy.example:8080",
    )

    audio_path = _download_youtube_audio(
        url="https://www.youtube.com/watch?v=abc123DEF_0",
        temp_dir=tmp_path,
    )

    options = calls["options"]
    assert audio_path.name == "audio_abc123DEF_0.m4a"
    assert calls["download"] is True
    assert options["proxy"] == "http://proxy-user:proxy-secret@proxy.example:8080"
    assert options["format"].startswith("bestaudio[acodec^=opus][abr<=96]")
    assert options["retries"] == 5
    assert options["http_chunk_size"] == 5 * 1024 * 1024


def test_modal_youtube_download_wraps_unserializable_provider_error(monkeypatch, tmp_path):
    from modal_apps import youtube_transcription

    class ProviderDownloadError(Exception):
        def __reduce__(self):
            raise TypeError("cannot pickle provider error")

    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, *_args, **_kwargs):
            raise ProviderDownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr(youtube_transcription.importlib_metadata, "version", lambda _name: "test")
    monkeypatch.setattr(youtube_transcription.shutil, "which", lambda _name: "/usr/local/bin/deno")

    with pytest.raises(RuntimeError, match="YouTube bot access challenge") as caught:
        youtube_transcription._download_youtube_audio(
            youtube_url="https://www.youtube.com/watch?v=abc123DEF_0",
            temp_dir=tmp_path,
        )

    assert caught.value.__cause__ is None
