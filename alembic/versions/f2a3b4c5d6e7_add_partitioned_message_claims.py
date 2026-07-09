"""Add partitioned message claims.

Revision ID: f2a3b4c5d6e7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-09 19:15:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARTITION_COUNT = 16


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS message_claims (
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
    for partition in range(PARTITION_COUNT):
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS message_claims_p{partition:02d}
            PARTITION OF message_claims
            FOR VALUES WITH (MODULUS {PARTITION_COUNT}, REMAINDER {partition})
            """
        )

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
