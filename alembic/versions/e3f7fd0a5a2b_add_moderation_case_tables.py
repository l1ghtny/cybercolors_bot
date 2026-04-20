"""add moderation case tables

Revision ID: e3f7fd0a5a2b
Revises: d9b8a8e6ef7f
Create Date: 2026-04-20 22:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e3f7fd0a5a2b"
down_revision = "d9b8a8e6ef7f"
branch_labels = None
depends_on = None


case_status_enum = postgresql.ENUM(
    "OPEN",
    "CLOSED",
    "ARCHIVED",
    name="casestatus",
    create_type=False,
)
evidence_type_enum = postgresql.ENUM(
    "SCREENSHOT",
    "LINK",
    "NOTE",
    "FILE",
    name="evidencetype",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE casestatus AS ENUM ('OPEN', 'CLOSED', 'ARCHIVED');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE evidencetype AS ENUM ('SCREENSHOT', 'LINK', 'NOTE', 'FILE');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "moderation_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=False),
        sa.Column("opened_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", case_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by_user_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_cases_server_id", "moderation_cases", ["server_id"], unique=False)
    op.create_index("ix_moderation_cases_target_user_id", "moderation_cases", ["target_user_id"], unique=False)
    op.create_index("ix_moderation_cases_status", "moderation_cases", ["status"], unique=False)

    op.create_table(
        "moderation_case_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["moderation_cases.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_case_notes_case_id", "moderation_case_notes", ["case_id"], unique=False)

    op.create_table(
        "moderation_case_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("added_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_type", evidence_type_enum, nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("attachment_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["moderation_cases.id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_case_evidence_case_id", "moderation_case_evidence", ["case_id"], unique=False)

    op.create_table(
        "moderation_case_action_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("moderation_action_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["moderation_cases.id"]),
        sa.ForeignKeyConstraint(["moderation_action_id"], ["moderation_actions.id"]),
        sa.ForeignKeyConstraint(["linked_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "moderation_action_id", name="uq_case_action_link"),
    )
    op.create_index(
        "ix_moderation_case_action_links_case_id",
        "moderation_case_action_links",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_case_action_links_moderation_action_id",
        "moderation_case_action_links",
        ["moderation_action_id"],
        unique=False,
    )

    op.create_table(
        "deleted_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("attachments_json", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_by_user_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["deleted_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deleted_messages_server_id", "deleted_messages", ["server_id"], unique=False)
    op.create_index("ix_deleted_messages_message_id", "deleted_messages", ["message_id"], unique=False)

    op.create_table(
        "moderation_action_deleted_message_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("moderation_action_id", sa.Uuid(), nullable=False),
        sa.Column("deleted_message_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["moderation_action_id"], ["moderation_actions.id"]),
        sa.ForeignKeyConstraint(["deleted_message_id"], ["deleted_messages.id"]),
        sa.ForeignKeyConstraint(["linked_by_user_id"], ["global_users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "moderation_action_id",
            "deleted_message_id",
            name="uq_action_deleted_message_link",
        ),
    )
    op.create_index(
        "ix_moderation_action_deleted_message_links_moderation_action_id",
        "moderation_action_deleted_message_links",
        ["moderation_action_id"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_action_deleted_message_links_deleted_message_id",
        "moderation_action_deleted_message_links",
        ["deleted_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_action_deleted_message_links_deleted_message_id",
        table_name="moderation_action_deleted_message_links",
    )
    op.drop_index(
        "ix_moderation_action_deleted_message_links_moderation_action_id",
        table_name="moderation_action_deleted_message_links",
    )
    op.drop_table("moderation_action_deleted_message_links")

    op.drop_index("ix_deleted_messages_message_id", table_name="deleted_messages")
    op.drop_index("ix_deleted_messages_server_id", table_name="deleted_messages")
    op.drop_table("deleted_messages")

    op.drop_index(
        "ix_moderation_case_action_links_moderation_action_id",
        table_name="moderation_case_action_links",
    )
    op.drop_index(
        "ix_moderation_case_action_links_case_id",
        table_name="moderation_case_action_links",
    )
    op.drop_table("moderation_case_action_links")

    op.drop_index("ix_moderation_case_evidence_case_id", table_name="moderation_case_evidence")
    op.drop_table("moderation_case_evidence")

    op.drop_index("ix_moderation_case_notes_case_id", table_name="moderation_case_notes")
    op.drop_table("moderation_case_notes")

    op.drop_index("ix_moderation_cases_status", table_name="moderation_cases")
    op.drop_index("ix_moderation_cases_target_user_id", table_name="moderation_cases")
    op.drop_index("ix_moderation_cases_server_id", table_name="moderation_cases")
    op.drop_table("moderation_cases")

    op.execute("DROP TYPE IF EXISTS evidencetype")
    op.execute("DROP TYPE IF EXISTS casestatus")
