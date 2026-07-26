import asyncio
from datetime import timezone
from uuid import uuid4

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.services.youtube_channels import index_youtube_channel_video, list_youtube_channel_videos
from src.db.database import engine
from src.db.models import AIKnowledgeIndexJob, AIKnowledgeSource, Server, YouTubeChannelSubscription, YouTubeChannelVideo
from src.modules.ai.youtube_channel_links import link_youtube_source_to_channel_video
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


def test_initial_channel_sync_catalogues_and_links_without_auto_indexing(monkeypatch):
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

    async def fake_upsert_profile(_session, _subscription):
        return None

    monkeypatch.setattr(
        "src.modules.ai.youtube_channel_sync.upsert_youtube_channel_profile",
        fake_upsert_profile,
    )

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
    assert catalogued[0].published_at.isoformat() == "2026-07-20T12:00:00+00:00"
    assert catalogued[0].published_at.tzinfo is timezone.utc
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

    async def fake_upsert_profile(_session, _subscription):
        return None

    monkeypatch.setattr(
        "src.modules.ai.youtube_channel_sync.upsert_youtube_channel_profile",
        fake_upsert_profile,
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


async def _database_timezone_scenario() -> None:
    await engine.dispose()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            server_id = 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)
            subscription = _subscription()
            subscription.server_id = server_id
            video = YouTubeVideo(
                video_id="tz123DEF_00",
                channel_id=subscription.channel_id,
                canonical_url="https://www.youtube.com/watch?v=tz123DEF_00",
                title="Timezone regression",
                description="",
                published_at="2026-07-20T14:00:00+02:00",
                duration_seconds=60,
                thumbnail_url=None,
                availability="available",
                captions_available=False,
            )

            async with AsyncSession(connection, expire_on_commit=False) as session:
                session.add(Server(server_id=server_id, server_name="timezone-test", bot_active=True))
                session.add(subscription)
                await session.flush()

                succeeded = await sync_youtube_channel_subscription(
                    session,
                    subscription,
                    client=_FakeClient(channel=_channel(), videos=[video]),
                    resolved_channel=_channel(),
                    auto_index_new=False,
                )
                await session.flush()
                session.expunge_all()
                persisted = (
                    await session.exec(
                        select(YouTubeChannelVideo).where(
                            YouTubeChannelVideo.subscription_id == subscription.id,
                            YouTubeChannelVideo.video_id == video.video_id,
                        )
                    )
                ).one()
                profile = (
                    await session.exec(
                        select(AIKnowledgeSource).where(
                            AIKnowledgeSource.server_id == server_id,
                            AIKnowledgeSource.source_type == "youtube_channel",
                        )
                    )
                ).one()
                profile_job = (
                    await session.exec(
                        select(AIKnowledgeIndexJob).where(
                            AIKnowledgeIndexJob.source_id == profile.id,
                        )
                    )
                ).one()

                assert succeeded is True
                assert persisted.published_at.isoformat() == "2026-07-20T12:00:00+00:00"
                assert persisted.published_at.utcoffset().total_seconds() == 0
                assert profile.status == "queued"
                assert "Known names and aliases: Studio Colors, @StudioColors, SC" in profile.content_text
                assert profile_job.status == "pending"

                transcript = AIKnowledgeSource(
                    server_id=server_id,
                    source_type="youtube",
                    subject_type="server",
                    status="ready",
                    visibility="public_answer",
                    title=video.title,
                    source_url=video.canonical_url,
                )
                session.add(transcript)
                await session.flush()
                linked = await link_youtube_source_to_channel_video(session, transcript)

                assert linked is not None
                assert linked.knowledge_source_id == transcript.id
        finally:
            await transaction.rollback()
    await engine.dispose()


def test_channel_sync_persists_provider_timestamp_in_postgresql():
    asyncio.run(_database_timezone_scenario())


async def _manual_video_index_scenario() -> None:
    await engine.dispose()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            server_id = 8_100_000_000_000_000 + (uuid4().int % 100_000_000_000_000)
            user_id = 8_200_000_000_000_000 + (uuid4().int % 100_000_000_000_000)
            subscription = _subscription()
            subscription.server_id = server_id
            video = YouTubeChannelVideo(
                subscription_id=subscription.id,
                server_id=server_id,
                video_id="manual12345",
                title="Needle manual indexing video",
                description="Searchable catalogue description",
                availability="available",
            )

            async with AsyncSession(connection, expire_on_commit=False) as session:
                session.add(Server(server_id=server_id, server_name="manual-index-test", bot_active=True))
                session.add(subscription)
                session.add(video)
                await session.flush()

                search_result = await list_youtube_channel_videos(
                    session,
                    server_id=server_id,
                    subscription_id=subscription.id,
                    search="needle",
                )
                missing_result = await list_youtube_channel_videos(
                    session,
                    server_id=server_id,
                    subscription_id=subscription.id,
                    search="not-present",
                )
                assert [item.video_id for item in search_result.items] == [video.video_id]
                assert missing_result.items == []

                indexed = await index_youtube_channel_video(
                    session,
                    server_id=server_id,
                    subscription_id=subscription.id,
                    video_id=video.video_id,
                    created_by_user_id=user_id,
                )
                assert indexed.knowledge_source_id is not None
                assert indexed.knowledge_source_status == "queued"

                repeated = await index_youtube_channel_video(
                    session,
                    server_id=server_id,
                    subscription_id=subscription.id,
                    video_id=video.video_id,
                    created_by_user_id=user_id,
                )
                jobs = (
                    await session.exec(
                        select(AIKnowledgeIndexJob).where(
                            AIKnowledgeIndexJob.source_id == video.knowledge_source_id,
                        )
                    )
                ).all()
                assert repeated.knowledge_source_id == indexed.knowledge_source_id
                assert len(jobs) == 1
        finally:
            await transaction.rollback()
    await engine.dispose()


def test_channel_video_search_and_manual_index_are_idempotent():
    asyncio.run(_manual_video_index_scenario())
