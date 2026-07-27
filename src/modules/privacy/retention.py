from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession


@dataclass(frozen=True)
class RetentionSettings:
    message_content_days: int = 30
    moderation_evidence_days: int = 365
    monitoring_event_days: int = 90
    bot_audit_days: int = 90
    batch_size: int = 2_000

    def __post_init__(self) -> None:
        values = {
            "message_content_days": self.message_content_days,
            "moderation_evidence_days": self.moderation_evidence_days,
            "monitoring_event_days": self.monitoring_event_days,
            "bot_audit_days": self.bot_audit_days,
            "batch_size": self.batch_size,
        }
        invalid = [name for name, value in values.items() if value < 1]
        if invalid:
            raise ValueError(f"Retention settings must be positive: {', '.join(invalid)}")
        if self.moderation_evidence_days < self.message_content_days:
            raise ValueError("moderation_evidence_days cannot be shorter than message_content_days")


_OPERATIONS: tuple[tuple[str, str], ...] = (
    (
        "message_attachments_deleted",
        """
        WITH candidates AS (
            SELECT ml.message_id
            FROM message_log AS ml
            WHERE (
                (
                    ml.created_at < :content_cutoff
                    AND NOT EXISTS (
                        SELECT 1 FROM moderation_action_message_links AS l
                        WHERE l.message_id = ml.message_id
                    )
                )
                OR (
                    ml.created_at < :evidence_cutoff
                    AND EXISTS (
                        SELECT 1 FROM moderation_action_message_links AS l
                        WHERE l.message_id = ml.message_id
                    )
                )
            )
            AND EXISTS (
                SELECT 1 FROM attachment_log AS a
                WHERE a.message_id = ml.message_id
            )
            ORDER BY ml.created_at, ml.message_id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM attachment_log AS a
        USING candidates AS c
        WHERE a.message_id = c.message_id
        """,
    ),
    (
        "message_contents_redacted",
        """
        WITH candidates AS (
            SELECT ml.message_id
            FROM message_log AS ml
            WHERE ml.content <> ''
            AND (
                (
                    ml.created_at < :content_cutoff
                    AND NOT EXISTS (
                        SELECT 1 FROM moderation_action_message_links AS l
                        WHERE l.message_id = ml.message_id
                    )
                )
                OR (
                    ml.created_at < :evidence_cutoff
                    AND EXISTS (
                        SELECT 1 FROM moderation_action_message_links AS l
                        WHERE l.message_id = ml.message_id
                    )
                )
            )
            ORDER BY ml.created_at, ml.message_id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE message_log AS ml
        SET content = ''
        FROM candidates AS c
        WHERE ml.message_id = c.message_id
        """,
    ),
    (
        "message_claims_deleted",
        """
        WITH candidates AS (
            SELECT message_id
            FROM message_claims
            WHERE claimed_at < :content_cutoff
            ORDER BY claimed_at, message_id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM message_claims AS mc
        USING candidates AS c
        WHERE mc.message_id = c.message_id
        """,
    ),
    (
        "unlinked_deleted_messages_deleted",
        """
        WITH candidates AS (
            SELECT dm.id
            FROM deleted_messages AS dm
            WHERE dm.deleted_at < :content_cutoff
            AND NOT EXISTS (
                SELECT 1 FROM moderation_action_deleted_message_links AS l
                WHERE l.deleted_message_id = dm.id
            )
            ORDER BY dm.deleted_at, dm.id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM deleted_messages AS dm
        USING candidates AS c
        WHERE dm.id = c.id
        """,
    ),
    (
        "linked_deleted_messages_redacted",
        """
        WITH candidates AS (
            SELECT dm.id
            FROM deleted_messages AS dm
            WHERE dm.deleted_at < :evidence_cutoff
            AND (dm.content IS NOT NULL OR dm.attachments_json IS NOT NULL)
            AND EXISTS (
                SELECT 1 FROM moderation_action_deleted_message_links AS l
                WHERE l.deleted_message_id = dm.id
            )
            ORDER BY dm.deleted_at, dm.id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE deleted_messages AS dm
        SET content = NULL, attachments_json = NULL
        FROM candidates AS c
        WHERE dm.id = c.id
        """,
    ),
    (
        "unlinked_ai_decisions_deleted",
        """
        WITH candidates AS (
            SELECT id
            FROM ai_moderation_decisions
            WHERE created_at < :content_cutoff
            AND linked_case_id IS NULL
            AND linked_action_id IS NULL
            ORDER BY created_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM ai_moderation_decisions AS d
        USING candidates AS c
        WHERE d.id = c.id
        """,
    ),
    (
        "linked_ai_decisions_redacted",
        """
        WITH candidates AS (
            SELECT id
            FROM ai_moderation_decisions
            WHERE created_at < :evidence_cutoff
            AND (linked_case_id IS NOT NULL OR linked_action_id IS NOT NULL)
            AND (
                message_content IS NOT NULL
                OR raw_response IS NOT NULL
                OR reason IS NOT NULL
                OR action_reason IS NOT NULL
                OR parse_error IS NOT NULL
                OR attachments_json::text <> '[]'
                OR policy_notes::text <> '[]'
            )
            ORDER BY created_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE ai_moderation_decisions AS d
        SET
            message_content = NULL,
            attachments_json = '[]'::json,
            reason = NULL,
            action_reason = NULL,
            policy_notes = '[]'::json,
            raw_response = NULL,
            parse_error = NULL
        FROM candidates AS c
        WHERE d.id = c.id
        """,
    ),
    (
        "ai_answer_logs_deleted",
        """
        WITH candidates AS (
            SELECT id
            FROM ai_answer_logs
            WHERE created_at < :content_cutoff
            ORDER BY created_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM ai_answer_logs AS logs
        USING candidates AS c
        WHERE logs.id = c.id
        """,
    ),
    (
        "monitoring_event_contents_redacted",
        """
        WITH candidates AS (
            SELECT id
            FROM monitored_user_activity_events
            WHERE occurred_at < :content_cutoff
            AND event_type IN ('message', 'image', 'ai_interaction')
            AND (message_content IS NOT NULL OR metadata_json::text <> '{}')
            ORDER BY occurred_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE monitored_user_activity_events AS events
        SET message_content = NULL, metadata_json = '{}'::json
        FROM candidates AS c
        WHERE events.id = c.id
        """,
    ),
    (
        "monitoring_events_deleted",
        """
        WITH candidates AS (
            SELECT id
            FROM monitored_user_activity_events
            WHERE occurred_at < :monitoring_cutoff
            ORDER BY occurred_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM monitored_user_activity_events AS events
        USING candidates AS c
        WHERE events.id = c.id
        """,
    ),
    (
        "bot_audit_events_deleted",
        """
        WITH candidates AS (
            SELECT id
            FROM bot_message_audit_events
            WHERE created_at < :bot_audit_cutoff
            ORDER BY created_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM bot_message_audit_events AS events
        USING candidates AS c
        WHERE events.id = c.id
        """,
    ),
    (
        "expired_dashboard_sessions_deleted",
        """
        WITH candidates AS (
            SELECT session_token_hash
            FROM dashboard_sessions
            WHERE expires_at < :now
            ORDER BY expires_at, session_token_hash
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM dashboard_sessions AS sessions
        USING candidates AS c
        WHERE sessions.session_token_hash = c.session_token_hash
        """,
    ),
)


async def run_retention_batch(
    session: AsyncSession,
    *,
    settings: RetentionSettings | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Apply one bounded, lock-skipping retention pass.

    Per-message identifiers and timestamps remain in ``message_log`` for
    aggregate activity features, but message text and attachment URLs expire.
    Content explicitly linked to a moderation action receives the longer
    evidence window before it is redacted.
    """

    effective_settings = settings or RetentionSettings()
    effective_now = now or datetime.now(UTC)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=UTC)

    params = {
        "now": effective_now,
        "content_cutoff": effective_now - timedelta(days=effective_settings.message_content_days),
        "evidence_cutoff": effective_now - timedelta(days=effective_settings.moderation_evidence_days),
        "monitoring_cutoff": effective_now - timedelta(days=effective_settings.monitoring_event_days),
        "bot_audit_cutoff": effective_now - timedelta(days=effective_settings.bot_audit_days),
        "batch_size": effective_settings.batch_size,
    }
    counts: dict[str, int] = {}
    for name, query in _OPERATIONS:
        result = await session.execute(sa.text(query), params)
        counts[name] = max(0, int(result.rowcount or 0))
    return counts
