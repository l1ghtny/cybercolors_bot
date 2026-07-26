import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from src.db.models import AIKnowledgeSource, GlobalUser, YouTubeChannelSubscription, YouTubeChannelVideo
from src.modules.ai import youtube_channel_catalog as youtube_channel_catalog_module
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
            mode="latest_videos",
            limit=5,
        )
    )

    assert result["channels"][0]["handle"] == "@StudioColors"
    assert result["channels"][0]["description"] == "A channel about theatre and production."
    assert result["videos"][0]["published_at"] == "2026-07-20T12:00:00Z"
    assert result["videos"][0]["transcript_available"] is True
    assert "channel_id" not in result["channels"][0]
    assert "video_id" not in result["videos"][0]
    assert "knowledge_source_id" not in result["videos"][0]
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

    assert result == {"channels": [], "videos": [], "transcript_matches": []}
    assert len(session.statements) == 1


def test_default_tool_registry_exposes_youtube_channel_catalog():
    registry = build_default_tool_registry()
    specs = {tool["name"]: tool for tool in registry.as_specs()}

    assert "search_youtube_channel_catalog" in specs
    tool = specs["search_youtube_channel_catalog"]
    assert tool["requires_admin_context"] is False
    assert "structured video dates" in tool["description"]


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
    assert session.params[0]["source_ids"] == [str(source_id)]
    assert "CAST(source.id AS text) IN" in str(session.statements[0])


def test_catalog_resolves_acronym_and_grammatical_name_variant():
    channel = _channel()
    channel.title = "Зона Веселья с Саней"
    channel.handle = "@studiocolors"
    session = _Session([[channel], [channel]])

    by_name = asyncio.run(
        search_youtube_channel_catalog(
            session,
            server_id=123,
            channel_query="канал Сани",
            mode="channel_info",
        )
    )
    by_acronym = asyncio.run(
        search_youtube_channel_catalog(
            session,
            server_id=123,
            channel_query="ЗВС",
            mode="channel_info",
        )
    )

    assert by_name["channels"][0]["name"] == "Зона Веселья с Саней"
    assert by_acronym["channels"][0]["name"] == "Зона Веселья с Саней"


def test_catalog_uses_indexed_channel_profile_for_semantic_resolution(monkeypatch):
    channel = _channel()
    profile = AIKnowledgeSource(
        id=uuid4(),
        server_id=123,
        source_type="youtube_channel",
        subject_type="server",
        status="ready",
        title=channel.title,
        content_text="A theatre production channel.",
        metadata_json={"youtube_channel": {"subscription_id": str(channel.id)}},
    )
    session = _Session([[channel], [profile]])

    async def fake_search(*_args, **kwargs):
        assert kwargs["source_ids"] == [str(profile.id)]
        return [{"source_id": str(profile.id), "score": 0.91}]

    monkeypatch.setattr(youtube_channel_catalog_module, "search_server_knowledge", fake_search)
    result = asyncio.run(
        search_youtube_channel_catalog(
            session,
            server_id=123,
            channel_query="the theatre production account",
            mode="channel_info",
        )
    )

    assert result["channels"] == [
        {
            "name": "Studio Colors",
            "handle": "@StudioColors",
            "known_as": ["SC", "StudioColors"],
            "related_members": [],
            "description": "A channel about theatre and production.",
            "url": channel.canonical_url,
        }
    ]
    assert len(session.statements) == 2


def test_channel_profile_returns_user_facing_aliases_and_related_member_names():
    channel = _channel()
    channel.aliases = ["Main theatre channel"]
    channel.related_user_ids = ["42"]
    session = _Session([[channel], [GlobalUser(discord_id=42, username="Sanya")]])

    result = asyncio.run(
        search_youtube_channel_catalog(
            session,
            server_id=123,
            channel_query="Studio Colors",
            mode="channel_info",
        )
    )

    assert result["channels"][0]["known_as"] == [
        "SC",
        "StudioColors",
        "Main theatre channel",
    ]
    assert result["channels"][0]["related_members"] == ["Sanya"]
