"""add moderation import tables

Revision ID: a6d4f9b2c801
Revises: 0d7b3a6e9c21
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a6d4f9b2c801"
down_revision = "0d7b3a6e9c21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_import_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("started_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["started_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_import_runs_server_id", "moderation_import_runs", ["server_id"], unique=False)
    op.create_index("ix_moderation_import_runs_source", "moderation_import_runs", ["source"], unique=False)
    op.create_index("ix_moderation_import_runs_status", "moderation_import_runs", ["status"], unique=False)

    op.create_table(
        "moderation_import_source_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_run_id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_item_type", sa.String(length=100), nullable=False),
        sa.Column("source_item_id", sa.String(length=255), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column("normalized_payload_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("moderation_action_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["import_run_id"], ["moderation_import_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["moderation_action_id"], ["moderation_actions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "source", "source_hash", name="uq_moderation_import_source_item"),
    )
    op.create_index("ix_moderation_import_source_items_import_run_id", "moderation_import_source_items", ["import_run_id"], unique=False)
    op.create_index("ix_moderation_import_source_items_moderation_action_id", "moderation_import_source_items", ["moderation_action_id"], unique=False)
    op.create_index("ix_moderation_import_source_items_server_id", "moderation_import_source_items", ["server_id"], unique=False)
    op.create_index("ix_moderation_import_source_items_source", "moderation_import_source_items", ["source"], unique=False)
    op.create_index("ix_moderation_import_source_items_source_hash", "moderation_import_source_items", ["source_hash"], unique=False)
    op.create_index("ix_moderation_import_source_items_source_item_type", "moderation_import_source_items", ["source_item_type"], unique=False)
    op.create_index("ix_moderation_import_source_items_status", "moderation_import_source_items", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_moderation_import_source_items_status", table_name="moderation_import_source_items")
    op.drop_index("ix_moderation_import_source_items_source_item_type", table_name="moderation_import_source_items")
    op.drop_index("ix_moderation_import_source_items_source_hash", table_name="moderation_import_source_items")
    op.drop_index("ix_moderation_import_source_items_source", table_name="moderation_import_source_items")
    op.drop_index("ix_moderation_import_source_items_server_id", table_name="moderation_import_source_items")
    op.drop_index("ix_moderation_import_source_items_moderation_action_id", table_name="moderation_import_source_items")
    op.drop_index("ix_moderation_import_source_items_import_run_id", table_name="moderation_import_source_items")
    op.drop_table("moderation_import_source_items")

    op.drop_index("ix_moderation_import_runs_status", table_name="moderation_import_runs")
    op.drop_index("ix_moderation_import_runs_source", table_name="moderation_import_runs")
    op.drop_index("ix_moderation_import_runs_server_id", table_name="moderation_import_runs")
    op.drop_table("moderation_import_runs")