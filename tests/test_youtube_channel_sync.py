import asyncio
from uuid import uuid4

from src.db.models import AIKnowledgeSource, YouTubeChannelSubscription, YouTubeChannelVideo
from src.modules.ai.youtube_channel_sync import sync_youtube_channel_subscription
from src.modules.ai.youtube_data import YouTubeChannel, YouTubeDataError, YouTubeVideo


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.added = []

    async def exec(self, _statement):
        return _Result(self.responses.pop(0))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


class _FakeClient:
    def __init__(self, *, channel, videos=None, error=None):
        self.channel = channel
        self.videos = videos or []
        self.error = error

    def resolve_channel(self, _value):
        return self.channel

    def list_uploads(self, _channel, *, max_videos):
        assert max_videos > 0
        if self.error:
            raise self.error
        return self.videos


def _channel() -> YouTubeChannel:
    return YouTubeChannel(
        channel_id="UC1234567890123456789012",
        handle="@StudioColors",
        custom_url="@StudioColors",
        canonical_url="https://www.youtube.com/channel/UC1234567890123456789012",
        title="Studio Colors",
        description="Channel description",
        thumbnail_url="https://img.test/channel.jpg",
        uploads_playlist_id="UU1234567890123456789012",
    )


def _subscription() -> YouTubeChannelSubscription:
    return YouTubeChannelSubscription(
        id=uuid4(),
        server_id=123,
        channel_id="UC1234567890123456789012",
        canonical_url="https://www.youtube.com/channel/UC1234567890123456789012",
        title="Studio Colors",
        uploads_playlist_id="UU1234567890123456789012",
        status="enabled",
        auto_index_new_videos=True,
    )


def test_initial_channel_sync_catalogues_and_links_without_auto_indexing():
    source = AIKnowledgeSource(
        id=uuid4(),
        server_id=123,
        source_type="youtube",
        subject_type="server",
        status="ready",
        visibility="public_answer",
        title="Existing transcript",
        source_url="https://www.youtube.com/watch?v=abc123DEF_0",
    )
    video = YouTubeVideo(
        video_id="abc123DEF_0",
        channel_id="UC1234567890123456789012",
        canonical_url="https://www.youtube.com/watch?v=abc123DEF_0",
        title="Existing video",
        description="Description",
        published_at="2026-07-20T12:00:00Z",
        duration_seconds=125,
        thumbnail_url="https://img.test/video.jpg",
        availability="available",
        captions_available=True,
    )
    session = _FakeSession([[], [source]])
    subscription = _subscription()

    succeeded = asyncio.run(
        sync_youtube_channel_subscription(
            session,
            subscription,
            client=_FakeClient(channel=_channel(), videos=[video]),
            resolved_channel=_channel(),
            auto_index_new=False,
        )
    )

    catalogued = [item for item in session.added if isinstance(item, YouTubeChannelVideo)]
    created_sources = [item for item in session.added if isinstance(item, AIKnowledgeSource)]
    assert succeeded is True
    assert len(catalogued) == 1
    assert catalogued[0].knowledge_source_id == source.id
    assert catalogued[0].published_at.isoformat() == "2026-07-20T12:00:00"
    assert catalogued[0].published_at.tzinfo is None
    assert created_sources == []
    assert subscription.status == "enabled"
    assert subscription.last_synced_at is not None


def test_channel_sync_persists_safe_retryable_error():
    session = _FakeSession([])
    subscription = _subscription()
    provider_error = YouTubeDataError("youtube_data_rate_limited", retryable=True, status_code=429)

    succeeded = asyncio.run(
        sync_youtube_channel_subscription(
            session,
            subscription,
            client=_FakeClient(channel=_channel(), error=provider_error),
            resolved_channel=_channel(),
        )
    )

    assert succeeded is False
    assert subscription.status == "error"
    assert subscription.error_code == "youtube_data_rate_limited"
    assert subscription.error_message == "YouTube temporarily limited channel synchronization."
    assert subscription.next_sync_at is not None


def test_subsequent_sync_auto_indexes_new_available_video(monkeypatch):
    created_source = AIKnowledgeSource(
        id=uuid4(),
        server_id=123,
        source_type="youtube",
        subject_type="server",
        status="queued",
        visibility="public_answer",
        title="New upload",
        source_url="https://www.youtube.com/watch?v=new123DEF_0",
    )
    created_for: list[str] = []

    async def fake_create_source(_session, *, subscription, video):
        assert subscription.auto_index_new_videos is True
        created_for.append(video.video_id)
        return created_source

    monkeypatch.setattr(
        "src.modules.ai.youtube_channel_sync._create_video_knowledge_source",
        fake_create_source,
    )
    video = YouTubeVideo(
        video_id="new123DEF_0",
        channel_id="UC1234567890123456789012",
        canonical_url="https://www.youtube.com/watch?v=new123DEF_0",
        title="New upload",
        description="",
        published_at="2026-07-24T10:00:00Z",
        duration_seconds=60,
        thumbnail_url=None,
        availability="available",
        captions_available=False,
    )
    session = _FakeSession([[], []])
    subscription = _subscription()

    succeeded = asyncio.run(
        sync_youtube_channel_subscription(
            session,
            subscription,
            client=_FakeClient(channel=_channel(), videos=[video]),
            resolved_channel=_channel(),
            auto_index_new=True,
        )
    )

    catalogued = [item for item in session.added if isinstance(item, YouTubeChannelVideo)]
    assert succeeded is True
    assert created_for == ["new123DEF_0"]
    assert catalogued[0].knowledge_source_id == created_source.id
