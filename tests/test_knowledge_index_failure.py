import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.modules.ai import knowledge


def test_embedding_failure_replaces_stale_transcription_error_and_processing_state(monkeypatch):
    job = SimpleNamespace(server_id=123, source_id="source", id="job", status="running", attempt_count=3)
    source = SimpleNamespace(server_id=123, status="processing", error_code="modal_transcription_failed",
                             error_message="old timeout", content_text="Saved successful transcript")
    session = SimpleNamespace(get=AsyncMock(return_value=source), flush=AsyncMock())
    monkeypatch.setattr(knowledge, "claim_next_knowledge_index_job", AsyncMock(return_value=job))
    monkeypatch.setattr(knowledge, "process_knowledge_index_job", AsyncMock(side_effect=RuntimeError("embedding unavailable")))
    assert asyncio.run(knowledge.run_knowledge_index_job_once(session))
    assert job.status == source.status == "failed"
    assert source.error_code == "indexing_failed"
    assert source.error_message == "embedding unavailable"
    assert source.content_text == "Saved successful transcript"
