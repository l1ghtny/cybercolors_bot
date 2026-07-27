import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.modules.privacy.retention import RetentionSettings, run_retention_batch


ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _RecordingSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return _Result(len(self.calls))


def test_retention_settings_reject_invalid_windows():
    with pytest.raises(ValueError, match="positive"):
        RetentionSettings(message_content_days=0)
    with pytest.raises(ValueError, match="cannot be shorter"):
        RetentionSettings(message_content_days=30, moderation_evidence_days=29)


def test_retention_index_migration_does_not_recreate_existing_answer_log_index():
    migration = (
        ROOT / "alembic" / "versions" / "d1e2f3a4b5c6_add_privacy_retention_indexes.py"
    ).read_text(encoding="utf-8")

    assert "CREATE INDEX IF NOT EXISTS ix_ai_moderation_decisions_created_at" in migration
    assert "ix_ai_answer_logs_created_at" not in migration


def test_retention_batch_uses_bounded_policy_cutoffs():
    async def scenario():
        now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
        settings = RetentionSettings(
            message_content_days=30,
            moderation_evidence_days=365,
            monitoring_event_days=60,
            bot_audit_days=45,
            batch_size=123,
        )
        session = _RecordingSession()

        counts = await run_retention_batch(session, settings=settings, now=now)

        assert len(session.calls) == 12
        assert set(counts) == {
            "message_attachments_deleted",
            "message_contents_redacted",
            "message_claims_deleted",
            "unlinked_deleted_messages_deleted",
            "linked_deleted_messages_redacted",
            "unlinked_ai_decisions_deleted",
            "linked_ai_decisions_redacted",
            "ai_answer_logs_deleted",
            "monitoring_event_contents_redacted",
            "monitoring_events_deleted",
            "bot_audit_events_deleted",
            "expired_dashboard_sessions_deleted",
        }
        assert list(counts.values()) == list(range(1, 13))
        for query, params in session.calls:
            assert "LIMIT :batch_size" in query
            assert "FOR UPDATE SKIP LOCKED" in query
            assert params["now"] == now
            assert params["content_cutoff"] == now - timedelta(days=30)
            assert params["evidence_cutoff"] == now - timedelta(days=365)
            assert params["monitoring_cutoff"] == now - timedelta(days=60)
            assert params["bot_audit_cutoff"] == now - timedelta(days=45)
            assert params["batch_size"] == 123

        dashboard_query = next(
            query for query, _params in session.calls if "FROM dashboard_sessions" in query
        )
        assert "SELECT session_token_hash" in dashboard_query
        assert "sessions.session_token_hash = c.session_token_hash" in dashboard_query

    asyncio.run(scenario())
