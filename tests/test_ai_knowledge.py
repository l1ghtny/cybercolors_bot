import asyncio
import shutil
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from starlette.routing import Match
from sqlmodel import SQLModel, select

from api.api_main import app
from api.models.ai_knowledge import AIKnowledgeSourceCreateModel, AIKnowledgeSourceUpdateModel
from api.services.ai_knowledge import (
    create_file_knowledge_source,
    create_knowledge_source,
    delete_knowledge_source,
    get_knowledge_source,
    list_knowledge_jobs,
    list_knowledge_sources,
    queue_knowledge_source_reindex,
    update_knowledge_source,
)
from src.db.database import engine, get_async_session
from src.db.models import AIKnowledgeChunk, AIKnowledgeSource, GlobalUser, Server
from src.modules.ai import embeddings as embeddings_module
from src.modules.ai.knowledge import (
    KNOWLEDGE_EMBEDDING_DIMENSIONS,
    build_knowledge_chunks,
    knowledge_source_index_text,
    run_knowledge_index_job_once,
    search_server_knowledge,
    upsert_admin_text_source,
)
from src.modules.ai.knowledge_imports import (
    KnowledgeImportError,
    ModalTranscriptionProvider,
    _extract_youtube_audio_and_transcribe,
    _select_caption_files,
)
from src.modules.ai.tools import build_default_tool_registry
from tests.db_helpers import ensure_pgvector_or_skip


class FakeKnowledgeEmbedder:
    provider_name = "fake"
    model = "fake-embedding"
    dimensions = KNOWLEDGE_EMBEDDING_DIMENSIONS

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            lower = text.lower()
            vector = [0.0] * self.dimensions
            if "art" in lower or "mina" in lower:
                vector[0] = 1.0
            if "movie" in lower or "friday" in lower:
                vector[1] = 1.0
            if not any(vector):
                vector[2] = 1.0
            embeddings.append(vector)
        return embeddings


def _make_discord_id() -> int:
    return 9_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


def _make_test_temp_dir() -> Path:
    temp_dir = Path("logs") / "test_ai_knowledge" / str(uuid4())
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _assert_route(path: str, method: str, expected_path: str):
    scope = {"type": "http", "method": method, "path": path}
    for route in app.routes:
        match, _child_scope = route.matches(scope)
        if match == Match.FULL:
            assert route.path == expected_path
            return
    raise AssertionError(f"Route did not match: {method} {path}")


def test_ai_knowledge_routes_are_registered():
    _assert_route("/servers/123/ai/knowledge", "GET", "/servers/{server_id}/ai/knowledge")
    _assert_route("/servers/123/ai/knowledge", "POST", "/servers/{server_id}/ai/knowledge")
    _assert_route("/servers/123/ai/knowledge/file", "POST", "/servers/{server_id}/ai/knowledge/file")
    _assert_route("/servers/123/ai/knowledge/search", "POST", "/servers/{server_id}/ai/knowledge/search")
    _assert_route("/servers/123/ai/knowledge/jobs", "GET", "/servers/{server_id}/ai/knowledge/jobs")
    _assert_route(
        "/servers/123/ai/knowledge/jobs/process-one",
        "POST",
        "/servers/{server_id}/ai/knowledge/jobs/process-one",
    )
    _assert_route(
        "/servers/123/ai/knowledge/11111111-1111-1111-1111-111111111111",
        "GET",
        "/servers/{server_id}/ai/knowledge/{source_id}",
    )
    _assert_route(
        "/servers/123/ai/knowledge/11111111-1111-1111-1111-111111111111/reindex",
        "POST",
        "/servers/{server_id}/ai/knowledge/{source_id}/reindex",
    )


def test_build_knowledge_chunks_normalizes_text_and_hashes_chunks():
    text = "  Server guide:\n\n" + " ".join(f"policy-{index}" for index in range(180))

    chunks = build_knowledge_chunks(text, target_tokens=80, max_tokens=110, overlap_words=8)

    assert len(chunks) > 1
    assert chunks[0]["chunk_ordinal"] == 0
    assert chunks[1]["chunk_ordinal"] == 1
    assert "\n" not in chunks[0]["chunk_text"]
    assert len(chunks[0]["text_hash"]) == 64
    assert chunks[0]["token_count"] > 0


def test_knowledge_source_index_text_includes_title_for_retrieval():
    index_text = knowledge_source_index_text(
        AIKnowledgeSource(
            server_id=123,
            source_type="text",
            subject_type="admin",
            title="Информация о lightny",
            content_text="Он администратор сервера и создатель этого бота.",
        )
    )

    assert "Title: Информация о lightny" in index_text
    assert "Он администратор" in index_text


def test_default_tool_registry_exposes_server_knowledge_search():
    registry = build_default_tool_registry()
    specs = {tool["name"]: tool for tool in registry.as_specs()}

    assert "search_server_knowledge" in specs
    assert specs["search_server_knowledge"]["requires_admin_context"] is False
    assert "approved public server/admin knowledge" in specs["search_server_knowledge"]["description"]


def test_build_knowledge_embedder_reuses_the_loaded_local_model(monkeypatch):
    created = []

    class FakeLocalEmbedder:
        def __init__(self, *, model, dimensions):
            self.provider_name = "local"
            self.model = model
            self.dimensions = dimensions
            created.append(self)

    embeddings_module._build_knowledge_embedder_cached.cache_clear()
    monkeypatch.setattr(embeddings_module, "LocalSentenceTransformerEmbedder", FakeLocalEmbedder)

    first = embeddings_module.build_knowledge_embedder()
    second = embeddings_module.build_knowledge_embedder()

    assert first is second
    assert created == [first]
    embeddings_module._build_knowledge_embedder_cached.cache_clear()


async def _knowledge_index_scenario() -> None:
    await engine.dispose()
    async with engine.begin() as conn:
        await ensure_pgvector_or_skip(conn)
        await conn.run_sync(SQLModel.metadata.create_all)

    server_id = _make_discord_id()
    admin_id = _make_discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="knowledge-test", bot_active=True))
        session.add(GlobalUser(discord_id=admin_id, username="admin"))
        await session.flush()

        source, job = await upsert_admin_text_source(
            session,
            server_id=server_id,
            title="Staff notes",
            content_text="Mina leads the art team. Server movie nights are on Fridays.",
            created_by_user_id=admin_id,
        )

        assert source.status == "queued"
        assert job.status == "pending"

        embedder = FakeKnowledgeEmbedder()
        processed = await run_knowledge_index_job_once(session, server_id=server_id, embedder=embedder)
        await session.refresh(source)

        chunks = (
            await session.exec(
                select(AIKnowledgeChunk).where(
                    AIKnowledgeChunk.server_id == server_id,
                    AIKnowledgeChunk.source_id == source.id,
                )
            )
        ).all()
        results = await search_server_knowledge(
            session,
            server_id=server_id,
            query="Who leads art?",
            limit=3,
            embedder=embedder,
        )

    assert processed is True
    assert source.status == "ready"
    assert len(chunks) == 1
    assert chunks[0].embedding is not None
    assert chunks[0].embedding_provider == "fake"
    assert chunks[0].embedding_model == "fake-embedding"
    assert results[0]["title"] == "Staff notes"
    assert "Mina leads the art team" in results[0]["text"]
    assert results[0]["distance"] < 0.3


def test_knowledge_source_can_be_queued_processed_and_searched():
    asyncio.run(_knowledge_index_scenario())


async def _knowledge_api_service_scenario() -> None:
    await engine.dispose()
    async with engine.begin() as conn:
        await ensure_pgvector_or_skip(conn)
        await conn.run_sync(SQLModel.metadata.create_all)

    server_id = _make_discord_id()
    actor_id = _make_discord_id()

    async with get_async_session() as session:
        source = await create_knowledge_source(
            session=session,
            server_id=server_id,
            created_by_user_id=actor_id,
            body=AIKnowledgeSourceCreateModel(
                title="Welcome info",
                content_text="The server owner is Mina.",
                queue_index=False,
            ),
        )
        assert source.status == "draft"
        assert source.source_type == "text"
        assert source.subject_type == "server"
        assert source.subject_user_id is None
        assert source.created_by_user_id == str(actor_id)

        admin_source = await create_knowledge_source(
            session=session,
            server_id=server_id,
            created_by_user_id=actor_id,
            body=AIKnowledgeSourceCreateModel(
                source_type="admin_note",
                subject_user_id=actor_id,
                title="Admin info",
                content_text="Mina helps with onboarding.",
                queue_index=False,
            ),
        )
        assert admin_source.source_type == "text"
        assert admin_source.subject_type == "admin"
        assert admin_source.subject_user_id == str(actor_id)

        listed = await list_knowledge_sources(session=session, server_id=server_id, subject_type="server")
        assert [item.id for item in listed.items] == [source.id]

        updated = await update_knowledge_source(
            session=session,
            server_id=server_id,
            source_id=UUID(source.id),
            body=AIKnowledgeSourceUpdateModel(content_text="The server owner is Mina. Events happen on Fridays."),
        )
        assert "Fridays" in updated.content_text

        job = await queue_knowledge_source_reindex(
            session=session,
            server_id=server_id,
            source_id=UUID(source.id),
        )
        assert job.status == "pending"

        jobs = await list_knowledge_jobs(session=session, server_id=server_id)
        assert jobs.items[0].id == job.id

        detail = await get_knowledge_source(
            session=session,
            server_id=server_id,
            source_id=UUID(source.id),
        )
        assert detail.status == "queued"

        await delete_knowledge_source(
            session=session,
            server_id=server_id,
            source_id=UUID(source.id),
        )
        deleted = await get_knowledge_source(
            session=session,
            server_id=server_id,
            source_id=UUID(source.id),
        )
        assert deleted.status == "deleted"
        assert deleted.deleted_at is not None


def test_knowledge_api_service_crud_and_reindex_queue():
    asyncio.run(_knowledge_api_service_scenario())


async def _knowledge_file_import_scenario() -> None:
    await engine.dispose()
    async with engine.begin() as conn:
        await ensure_pgvector_or_skip(conn)
        await conn.run_sync(SQLModel.metadata.create_all)

    server_id = _make_discord_id()
    actor_id = _make_discord_id()

    async with get_async_session() as session:
        source = await create_file_knowledge_source(
            session=session,
            server_id=server_id,
            created_by_user_id=actor_id,
            title="Uploaded staff guide",
            payload=b"Mina leads the art team from an uploaded guide.",
            filename="guide.txt",
            content_type="text/plain",
        )
        assert source.source_type == "file"
        assert source.status == "queued"
        assert source.storage_key is not None
        assert source.sha256 is not None

        embedder = FakeKnowledgeEmbedder()
        processed = await run_knowledge_index_job_once(session, server_id=server_id, embedder=embedder)
        detail = await get_knowledge_source(session=session, server_id=server_id, source_id=UUID(source.id))

        results = await search_server_knowledge(
            session,
            server_id=server_id,
            query="Who leads art?",
            limit=3,
            embedder=embedder,
        )

    assert processed is True
    assert detail.status == "ready"
    assert "uploaded guide" in (detail.content_text or "")
    assert detail.metadata_json["import"]["parser"] == "plain-text"
    assert results[0]["source_type"] == "file"
    assert "Mina leads the art team" in results[0]["text"]


def test_knowledge_file_source_can_be_uploaded_processed_and_searched():
    asyncio.run(_knowledge_file_import_scenario())


async def _knowledge_youtube_import_scenario(monkeypatch) -> None:
    await engine.dispose()
    async with engine.begin() as conn:
        await ensure_pgvector_or_skip(conn)
        await conn.run_sync(SQLModel.metadata.create_all)

    server_id = _make_discord_id()
    actor_id = _make_discord_id()

    def fake_extract_text_from_youtube_url(url: str):
        assert url == "https://www.youtube.com/watch?v=test123"
        return "Mina says movie night happens every Friday.", {
            "provider": "test",
            "video_id": "test123",
            "video_title": "Server update",
            "extracted_chars": 43,
        }

    monkeypatch.setattr(
        "src.modules.ai.knowledge.extract_text_from_youtube_url",
        fake_extract_text_from_youtube_url,
    )

    async with get_async_session() as session:
        source = await create_knowledge_source(
            session=session,
            server_id=server_id,
            created_by_user_id=actor_id,
            body=AIKnowledgeSourceCreateModel(
                source_type="youtube",
                title="YouTube server update",
                source_url="https://www.youtube.com/watch?v=test123",
            ),
        )

        embedder = FakeKnowledgeEmbedder()
        processed = await run_knowledge_index_job_once(session, server_id=server_id, embedder=embedder)
        detail = await get_knowledge_source(session=session, server_id=server_id, source_id=UUID(source.id))

        results = await search_server_knowledge(
            session,
            server_id=server_id,
            query="When is movie night?",
            limit=3,
            embedder=embedder,
        )

    assert processed is True
    assert detail.status == "ready"
    assert "movie night" in (detail.content_text or "")
    assert detail.metadata_json["import"]["provider"] == "test"
    assert results[0]["source_type"] == "youtube"
    assert "Friday" in results[0]["text"]


def test_knowledge_youtube_source_extracts_captions_before_indexing(monkeypatch):
    asyncio.run(_knowledge_youtube_import_scenario(monkeypatch))


def test_youtube_caption_selection_prefers_configured_language_order():
    temp_dir = _make_test_temp_dir()
    try:
        en = temp_dir / "video.en.vtt"
        ru = temp_dir / "video.ru.vtt"
        en.write_text("small", encoding="utf-8")
        ru.write_text("larger russian caption", encoding="utf-8")

        selected = _select_caption_files(temp_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert selected[0].name == "video.en.vtt"


def test_modal_transcription_provider_accepts_text_response():
    temp_dir = _make_test_temp_dir()
    audio_path = temp_dir / "audio.webm"
    audio_path.write_bytes(b"fake-audio")

    class FakeFunction:
        def __init__(self):
            self.timeout = None
            self.calls = []

        def with_options(self, *, timeout):
            self.timeout = timeout
            return self

        def remote(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "text": "hello from modal",
                "language": "en",
                "model": "large-v3",
                "segments": [{"start": 0, "end": 1, "text": "hello"}],
            }

    fake_function = FakeFunction()
    try:
        provider = ModalTranscriptionProvider(
            app_name="cybercolors-youtube-transcription",
            callable_type="class",
            class_name="YouTubeWhisperTranscriber",
            method_name="transcribe_audio",
            timeout_seconds=123,
            remote_handle=fake_function,
        )
        result = provider.transcribe(
            audio_path=audio_path,
            source_url="https://youtube.test/video",
            source_metadata={"video_id": "abc"},
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert result["text"] == "hello from modal"
    assert result["language"] == "en"
    assert result["model"] == "large-v3"
    assert result["segments_count"] == 1
    assert fake_function.timeout is None
    assert fake_function.calls[0]["filename"] == "audio.webm"
    assert fake_function.calls[0]["content_type"] == "audio/webm"
    assert fake_function.calls[0]["audio_bytes"] == b"fake-audio"
    assert fake_function.calls[0]["youtube_url"] == ""


def test_modal_transcription_provider_applies_timeout_to_function_handles():
    temp_dir = _make_test_temp_dir()
    audio_path = temp_dir / "audio.webm"
    audio_path.write_bytes(b"fake-audio")

    class FakeFunction:
        def __init__(self):
            self.timeout = None

        def with_options(self, *, timeout):
            self.timeout = timeout
            return self

        def remote(self, **kwargs):
            return {"text": "hello from modal"}

    fake_function = FakeFunction()
    try:
        provider = ModalTranscriptionProvider(
            app_name="cybercolors-youtube-transcription",
            callable_type="function",
            function_name="transcribe_audio",
            timeout_seconds=123,
            remote_handle=fake_function,
        )
        result = provider.transcribe(
            audio_path=audio_path,
            source_url="https://youtube.test/video",
            source_metadata={"video_id": "abc"},
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert result["text"] == "hello from modal"
    assert fake_function.timeout == 123


def test_modal_transcription_provider_requires_endpoint():
    temp_dir = _make_test_temp_dir()
    audio_path = temp_dir / "audio.webm"
    audio_path.write_bytes(b"fake-audio")
    provider = ModalTranscriptionProvider(app_name="")

    try:
        try:
            provider.transcribe(audio_path=audio_path, source_url="https://youtube.test/video", source_metadata={})
        except KnowledgeImportError as exc:
            assert exc.code == "modal_transcription_not_configured"
        else:
            raise AssertionError("Expected KnowledgeImportError")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_youtube_audio_fallback_uses_modal_provider(monkeypatch):
    temp_dir = _make_test_temp_dir()

    class FakeModalProvider:
        def transcribe_youtube(self, *, youtube_url, source_url, source_metadata):
            assert youtube_url == "https://youtube.test/video"
            assert source_url == "https://youtube.test/video"
            assert source_metadata["video_id"] == "abc"
            return {
                "text": "Mina talks about Friday movie nights.",
                "language": "en",
                "model": "whisper-large-v3",
                "segments_count": 2,
            }

    monkeypatch.setattr("src.modules.ai.knowledge_imports.ModalTranscriptionProvider", FakeModalProvider)

    try:
        text, metadata = _extract_youtube_audio_and_transcribe(
            url="https://youtube.test/video",
            info={"id": "abc", "title": "Server update", "duration": 42, "webpage_url": "https://youtube.test/video"},
            temp_dir=temp_dir,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert text == "Mina talks about Friday movie nights."
    assert metadata["provider"] == "modal"
    assert metadata["mode"] == "audio_transcription"
    assert metadata["transcription_model"] == "whisper-large-v3"


def test_youtube_audio_fallback_uploads_local_audio_when_modal_youtube_is_blocked(monkeypatch):
    temp_dir = _make_test_temp_dir()
    downloaded_audio = temp_dir / "audio.webm"
    downloaded_audio.write_bytes(b"fake-youtube-audio")

    class FakeModalProvider:
        def transcribe_youtube(self, *, youtube_url, source_url, source_metadata):
            raise KnowledgeImportError(
                "modal_transcription_failed",
                "ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies for auth.",
            )

        def transcribe(self, *, audio_path, source_url, source_metadata):
            assert audio_path == downloaded_audio
            assert source_metadata["modal_youtube_error"]
            return {
                "text": "Mina talks about Friday movie nights.",
                "language": "en",
                "model": "whisper-large-v3",
                "segments_count": 2,
            }

    def fake_download_youtube_audio(*, url, temp_dir):
        assert url == "https://youtube.test/video"
        return downloaded_audio

    monkeypatch.setattr("src.modules.ai.knowledge_imports.ModalTranscriptionProvider", FakeModalProvider)
    monkeypatch.setattr("src.modules.ai.knowledge_imports._download_youtube_audio", fake_download_youtube_audio)

    try:
        text, metadata = _extract_youtube_audio_and_transcribe(
            url="https://youtube.test/video",
            info={"id": "abc", "title": "Server update", "duration": 42, "webpage_url": "https://youtube.test/video"},
            temp_dir=temp_dir,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert text == "Mina talks about Friday movie nights."
    assert metadata["provider"] == "modal"
    assert metadata["fallback_mode"] == "local_audio_upload"
    assert metadata["transcription_model"] == "whisper-large-v3"
