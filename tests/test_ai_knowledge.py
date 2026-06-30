import asyncio
from uuid import UUID
from uuid import uuid4

from starlette.routing import Match
from sqlmodel import SQLModel, select

from api.api_main import app
from api.models.ai_knowledge import AIKnowledgeSourceCreateModel, AIKnowledgeSourceUpdateModel
from api.services.ai_knowledge import (
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
from src.modules.ai.knowledge import (
    build_knowledge_chunks,
    knowledge_source_index_text,
    run_knowledge_index_job_once,
    search_server_knowledge,
    upsert_admin_text_source,
)
from src.modules.ai.tools import build_default_tool_registry
from tests.db_helpers import ensure_pgvector_or_skip


class FakeKnowledgeEmbedder:
    provider_name = "fake"
    model = "fake-embedding"
    dimensions = 1536

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
        processed = await run_knowledge_index_job_once(session, embedder=embedder)
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
