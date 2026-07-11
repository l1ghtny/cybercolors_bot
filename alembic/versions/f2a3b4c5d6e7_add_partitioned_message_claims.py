"""Add partitioned message claims.

Revision ID: f2a3b4c5d6e7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-09 19:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARTITION_COUNT = 16


def _message_claims_relation_kind() -> str | None:
    return op.get_bind().execute(
        sa.text(
            "SELECT relkind::text FROM pg_class "
            "WHERE oid = to_regclass('message_claims')"
        )
    ).scalar_one_or_none()


def _create_partitioned_message_claims_table() -> None:
    op.execute(
        """
        CREATE TABLE message_claims (
            message_id BIGINT NOT NULL,
            server_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            claimed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            PRIMARY KEY (message_id)
        ) PARTITION BY HASH (message_id)
        """
    )


def upgrade() -> None:
    relation_kind = _message_claims_relation_kind()
    needs_legacy_copy = relation_kind == "r"

    if needs_legacy_copy:
        op.execute("ALTER TABLE message_claims RENAME TO message_claims_legacy")
        _create_partitioned_message_claims_table()
    elif relation_kind is None:
        _create_partitioned_message_claims_table()
    elif relation_kind != "p":
        raise RuntimeError(
            "message_claims exists but is neither a regular nor partitioned table"
        )

    for partition in range(PARTITION_COUNT):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS message_claims_p{partition:02d}
            PARTITION OF message_claims
            FOR VALUES WITH (MODULUS {PARTITION_COUNT}, REMAINDER {partition})
            """
        )

    if needs_legacy_copy:
        op.execute(
            """
            INSERT INTO message_claims (
                message_id, server_id, channel_id, user_id, created_at, claimed_at
            )
            SELECT message_id, server_id, channel_id, user_id, created_at, claimed_at
            FROM message_claims_legacy
            ON CONFLICT (message_id) DO NOTHING
            """
        )
        op.execute("DROP TABLE message_claims_legacy")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_claims_server_created_at "
        "ON message_claims (server_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_claims_server_user_created_at "
        "ON message_claims (server_id, user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_claims_claimed_at "
        "ON message_claims (claimed_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_claims_claimed_at")
    op.execute("DROP INDEX IF EXISTS ix_message_claims_server_user_created_at")
    op.execute("DROP INDEX IF EXISTS ix_message_claims_server_created_at")
    op.execute("DROP TABLE IF EXISTS message_claims CASCADE")
