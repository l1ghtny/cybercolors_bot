import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from src.db.models import YouTubeChannelSubscription, YouTubeChannelVideo
from src.modules.ai.knowledge import search_server_knowledge
from src.modules.ai.tools import build_default_tool_registry
from src.modules.ai.youtube_channel_catalog import search_youtube_channel_catalog


class _Result:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _Session:
    def __init__(self, results):
        self._results = iter(results)
        self.statements = []
        self.params = []

    async def exec(self, statement, *, params=None):
        self.statements.append(statement)
        self.params.append(params)
        return _Result(next(self._results))


class _Embedder:
    provider_name = "test"

    async def embed_texts(self, texts):
        return [[0.25] * 1_024 for _ in texts]


def _channel() -> YouTubeChannelSubscription:
    return YouTubeChannelSubscription(
        id=uuid4(),
        server_id=123,
        channel_id="UC1234567890123456789012",
        handle="@StudioColors",
        canonical_url="https://www.youtube.com/channel/UC1234567890123456789012",
        title="Studio Colors",
        description="A channel about theatre and production.",
        uploads_playlist_id="UU1234567890123456789012",
        status="enabled",
        last_synced_at=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
    )


def test_catalog_returns_channel_video_dates_and_transcript_status():
    channel = _channel()
    source_id = uuid4()
    video = YouTubeChannelVideo(
        id=uuid4(),
        subscription_id=channel.id,
        server_id=123,
        video_id="abcdefghijk",
        title="Behind the scenes",
        description="How the new production was made.",
        published_at=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
        duration_seconds=615,
        availability="available",
        knowledge_source_id=source_id,
    )
    session = _Session([[channel], [(video, channel, "ready")]])

    result = asyncio.run(
        search_youtube_channel_catalog(
            session,
            server_id=123,
            channel_query="Studio Colors",
            limit=5,
        )
    )

    assert result["channels"][0]["handle"] == "@StudioColors"
    assert result["channels"][0]["description"] == "A channel about theatre and production."
    assert result["videos"][0]["published_at"] == "2026-07-20T12:00:00Z"
    assert result["videos"][0]["has_indexed_transcript"] is True
    assert result["videos"][0]["knowledge_source_id"] == str(source_id)
    assert len(session.statements) == 2


def test_catalog_returns_no_videos_when_channel_does_not_match():
    session = _Session([[]])

    result = asyncio.run(
        search_youtube_channel_catalog(
            session,
            server_id=123,
            channel_query="Missing channel",
        )
    )

    assert result == {"channels": [], "videos": [], "returned_video_count": 0}
    assert len(session.statements) == 1


def test_default_tool_registry_exposes_youtube_channel_catalog():
    registry = build_default_tool_registry()
    specs = {tool["name"]: tool for tool in registry.as_specs()}

    assert "search_youtube_channel_catalog" in specs
    tool = specs["search_youtube_channel_catalog"]
    assert tool["requires_admin_context"] is False
    assert "publication dates" in tool["description"]


def test_server_knowledge_can_be_scoped_to_linked_transcript():
    source_id = uuid4()
    session = _Session([[]])

    result = asyncio.run(
        search_server_knowledge(
            session,
            server_id=123,
            query="What was announced?",
            source_id=str(source_id),
            embedder=_Embedder(),
        )
    )

    assert result == []
    assert session.params[0]["source_id"] == str(source_id)
    assert "source.id = CAST(:source_id AS uuid)" in str(session.statements[0])
