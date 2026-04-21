"""Add moderation rules and link them to moderation actions.

Revision ID: 8c1d7e4ab222
Revises: 6b3e4f2a9d10
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = "8c1d7e4ab222"
down_revision = "6b3e4f2a9d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("source_marker", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_rules_server_id", "moderation_rules", ["server_id"], unique=False)
    op.create_index("ix_moderation_rules_code", "moderation_rules", ["code"], unique=False)
    op.create_index("ix_moderation_rules_is_active", "moderation_rules", ["is_active"], unique=False)

    op.add_column("moderation_actions", sa.Column("rule_id", sa.Uuid(), nullable=True))
    op.add_column("moderation_actions", sa.Column("commentary", sa.Text(), nullable=True))
    op.create_index("ix_moderation_actions_rule_id", "moderation_actions", ["rule_id"], unique=False)
    op.create_foreign_key(
        "fk_moderation_actions_rule_id_moderation_rules",
        "moderation_actions",
        "moderation_rules",
        ["rule_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_moderation_actions_rule_id_moderation_rules", "moderation_actions", type_="foreignkey")
    op.drop_index("ix_moderation_actions_rule_id", table_name="moderation_actions")
    op.drop_column("moderation_actions", "commentary")
    op.drop_column("moderation_actions", "rule_id")

    op.drop_index("ix_moderation_rules_is_active", table_name="moderation_rules")
    op.drop_index("ix_moderation_rules_code", table_name="moderation_rules")
    op.drop_index("ix_moderation_rules_server_id", table_name="moderation_rules")
    op.drop_table("moderation_rules")
