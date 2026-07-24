import logging

import pytest
import requests

from src.modules.ai.youtube_data import (
    YouTubeChannel,
    YouTubeDataClient,
    YouTubeDataError,
    parse_youtube_duration_seconds,
)


CHANNEL_ID = "UCabc123DEF_012345678901"


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _channel_payload():
    return {
        "items": [
            {
                "id": CHANNEL_ID,
                "snippet": {
                    "title": "Studio Colors",
                    "description": "Channel description",
                    "customUrl": "@StudioColors",
                    "thumbnails": {
                        "default": {"url": "https://images.example/default.jpg"},
                        "high": {"url": "https://images.example/high.jpg"},
                    },
                },
                "contentDetails": {
                    "relatedPlaylists": {"uploads": "UUabc123DEF_012345678901"}
                },
            }
        ]
    }


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)

    with pytest.raises(YouTubeDataError) as caught:
        YouTubeDataClient()

    assert caught.value.code == "youtube_data_not_configured"
    assert "API" not in str(caught.value)


@pytest.mark.parametrize(
    ("value", "parameter", "lookup"),
    [
        ("@StudioColors", "forHandle", "@StudioColors"),
        ("youtube.com/@StudioColors", "forHandle", "@StudioColors"),
        (
            "youtube.com/@StudioColors/videos?view=0#uploads",
            "forHandle",
            "@StudioColors",
        ),
        ("youtube.com/@СтудияЦвета", "forHandle", "@СтудияЦвета"),
        (f"https://www.youtube.com/channel/{CHANNEL_ID}", "id", CHANNEL_ID),
        ("https://youtube.com/user/studio-colors", "forUsername", "studio-colors"),
        ("https://youtube.com/c/StudioColors", "forHandle", "StudioColors"),
    ],
)
def test_resolves_supported_channel_identifiers(value, parameter, lookup):
    session = FakeSession([FakeResponse(_channel_payload())])
    client = YouTubeDataClient(api_key="secret-key", session=session)

    channel = client.resolve_channel(value)

    assert channel.channel_id == CHANNEL_ID
    assert channel.handle == "@StudioColors"
    assert channel.custom_url == "@StudioColors"
    assert channel.canonical_url == f"https://www.youtube.com/channel/{CHANNEL_ID}"
    assert channel.title == "Studio Colors"
    assert channel.description == "Channel description"
    assert channel.thumbnail_url == "https://images.example/high.jpg"
    assert channel.uploads_playlist_id == "UUabc123DEF_012345678901"
    assert session.calls[0]["params"][parameter] == lookup
    assert session.calls[0]["params"]["part"] == "snippet,contentDetails"
    assert session.calls[0]["timeout"] == (3.05, 15.0)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://example.com/@StudioColors",
        "https://youtube.com/watch?v=abc123DEF_0",
        "https://youtube.com/playlist?list=PL123",
    ],
)
def test_rejects_invalid_channel_identifiers_before_request(value):
    session = FakeSession([])
    client = YouTubeDataClient(api_key="secret-key", session=session)

    with pytest.raises(YouTubeDataError) as caught:
        client.resolve_channel(value)

    assert caught.value.code == "youtube_channel_url_invalid"
    assert session.calls == []


def test_lists_uploads_with_pagination_limit_and_enrichment_batches():
    first_page_items = [_playlist_item(index) for index in range(50)]
    second_page_items = [_playlist_item(index) for index in range(50, 55)]
    first_video_batch = [_video_item(index) for index in range(50)]
    second_video_batch = [_video_item(index) for index in range(50, 55)]
    session = FakeSession(
        [
            FakeResponse({"items": first_page_items, "nextPageToken": "next"}),
            FakeResponse({"items": second_page_items}),
            FakeResponse({"items": first_video_batch}),
            FakeResponse({"items": second_video_batch}),
        ]
    )
    client = YouTubeDataClient(api_key="secret-key", session=session)

    videos = client.list_uploads(_channel(), max_videos=55)

    assert len(videos) == 55
    assert videos[0].video_id == "video000000"
    assert videos[0].title == "Video 0"
    assert videos[0].published_at == "2026-07-01T12:00:00Z"
    assert videos[0].duration_seconds == 3723
    assert videos[0].thumbnail_url == "https://images.example/video-0.jpg"
    assert videos[0].availability == "available"
    assert videos[0].captions_available is True
    assert session.calls[0]["params"]["maxResults"] == 50
    assert session.calls[1]["params"]["pageToken"] == "next"
    assert session.calls[1]["params"]["maxResults"] == 5
    assert len(session.calls[2]["params"]["id"].split(",")) == 50
    assert len(session.calls[3]["params"]["id"].split(",")) == 5


def test_preserves_unavailable_playlist_item_when_video_details_are_absent():
    session = FakeSession(
        [
            FakeResponse({"items": [_playlist_item(0)]}),
            FakeResponse({"items": []}),
        ]
    )
    client = YouTubeDataClient(api_key="secret-key", session=session)

    videos = client.list_uploads(_channel(), max_videos=1)

    assert videos[0].title == "Playlist Video 0"
    assert videos[0].duration_seconds is None
    assert videos[0].availability == "unavailable"
    assert videos[0].captions_available is None


@pytest.mark.parametrize(
    ("duration", "seconds"),
    [
        ("PT0S", 0),
        ("PT3M7S", 187),
        ("PT1H2M3S", 3723),
        ("P1DT2H", 93600),
    ],
)
def test_parses_youtube_iso8601_duration(duration, seconds):
    assert parse_youtube_duration_seconds(duration) == seconds


def test_classifies_quota_errors_without_exposing_key_or_provider_message(caplog):
    api_key = "super-secret-api-key"
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": {
                        "message": f"Provider echoed {api_key}",
                        "errors": [{"reason": "quotaExceeded"}],
                    }
                },
                status_code=403,
            )
        ]
    )
    client = YouTubeDataClient(api_key=api_key, session=session)

    with caplog.at_level(logging.WARNING), pytest.raises(YouTubeDataError) as caught:
        client.resolve_channel("@StudioColors")

    assert caught.value.code == "youtube_data_quota_exceeded"
    assert caught.value.retryable is True
    assert caught.value.status_code == 403
    assert api_key not in str(caught.value)
    assert api_key not in caplog.text
    assert "Provider echoed" not in caplog.text


def test_network_error_is_retryable_and_does_not_log_request_url(caplog):
    api_key = "super-secret-api-key"
    session = FakeSession([requests.ConnectionError(f"request?key={api_key}")])
    client = YouTubeDataClient(api_key=api_key, session=session)

    with caplog.at_level(logging.WARNING), pytest.raises(YouTubeDataError) as caught:
        client.resolve_channel("@StudioColors")

    assert caught.value.code == "youtube_data_request_failed"
    assert caught.value.retryable is True
    assert api_key not in caplog.text


def test_rejects_unbounded_timeout():
    with pytest.raises(ValueError, match="between 0 and 30 seconds"):
        YouTubeDataClient(api_key="secret-key", timeout=(3.0, 31.0))


def _channel():
    return YouTubeChannel(
        channel_id=CHANNEL_ID,
        handle="@StudioColors",
        custom_url="@StudioColors",
        canonical_url=f"https://www.youtube.com/channel/{CHANNEL_ID}",
        title="Studio Colors",
        description="Channel description",
        thumbnail_url=None,
        uploads_playlist_id="UUabc123DEF_012345678901",
    )


def _playlist_item(index):
    video_id = f"video{index:06d}"
    return {
        "contentDetails": {"videoId": video_id},
        "snippet": {
            "title": f"Playlist Video {index}",
            "description": f"Playlist Description {index}",
            "publishedAt": "2026-07-01T12:00:00Z",
            "thumbnails": {"default": {"url": f"https://images.example/playlist-{index}.jpg"}},
        },
    }


def _video_item(index):
    video_id = f"video{index:06d}"
    return {
        "id": video_id,
        "snippet": {
            "channelId": CHANNEL_ID,
            "title": f"Video {index}",
            "description": f"Description {index}",
            "publishedAt": "2026-07-01T12:00:00Z",
            "thumbnails": {"high": {"url": f"https://images.example/video-{index}.jpg"}},
        },
        "contentDetails": {"duration": "PT1H2M3S", "caption": "true"},
        "status": {"uploadStatus": "processed", "privacyStatus": "public"},
    }
