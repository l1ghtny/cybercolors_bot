"""add moderation rule citations and canonical action case link

Revision ID: f9a5c31d7e42
Revises: 5d2a9f1c7b3e
Create Date: 2026-04-26
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f9a5c31d7e42"
down_revision = "5d2a9f1c7b3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("moderation_actions", sa.Column("case_id", sa.Uuid(), nullable=True))
    op.create_index("ix_moderation_actions_case_id", "moderation_actions", ["case_id"], unique=False)
    op.create_foreign_key(
        "fk_moderation_actions_case_id_moderation_cases",
        "moderation_actions",
        "moderation_cases",
        ["case_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "moderation_action_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_code_snapshot", sa.String(), nullable=True),
        sa.Column("rule_title_snapshot", sa.String(), nullable=False),
        sa.Column("cited_at", sa.DateTime(), nullable=False),
        sa.Column("rule_deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["action_id"], ["moderation_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["moderation_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", "rule_id", name="uq_action_rule_citation"),
    )
    op.create_index("ix_moderation_action_rules_action_id", "moderation_action_rules", ["action_id"], unique=False)
    op.create_index("ix_moderation_action_rules_rule_id", "moderation_action_rules", ["rule_id"], unique=False)
    op.create_index("ix_moderation_action_rules_server_id", "moderation_action_rules", ["server_id"], unique=False)

    op.create_table(
        "moderation_case_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_code_snapshot", sa.String(), nullable=True),
        sa.Column("rule_title_snapshot", sa.String(), nullable=False),
        sa.Column("cited_at", sa.DateTime(), nullable=False),
        sa.Column("rule_deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["moderation_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["moderation_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "rule_id", name="uq_case_rule_citation"),
    )
    op.create_index("ix_moderation_case_rules_case_id", "moderation_case_rules", ["case_id"], unique=False)
    op.create_index("ix_moderation_case_rules_rule_id", "moderation_case_rules", ["rule_id"], unique=False)
    op.create_index("ix_moderation_case_rules_server_id", "moderation_case_rules", ["server_id"], unique=False)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION moderation_rules_before_delete_citation_cleanup()
        RETURNS trigger AS $$
        BEGIN
            UPDATE moderation_action_rules
            SET rule_deleted_at = NOW(),
                rule_id = NULL
            WHERE rule_id = OLD.id;

            UPDATE moderation_case_rules
            SET rule_deleted_at = NOW(),
                rule_id = NULL
            WHERE rule_id = OLD.id;

            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_moderation_rules_before_delete_citation_cleanup
        BEFORE DELETE ON moderation_rules
        FOR EACH ROW
        EXECUTE FUNCTION moderation_rules_before_delete_citation_cleanup();
        """
    )

    op.alter_column("moderation_case_notes", "author_user_id", existing_type=sa.BigInteger(), nullable=True)

    op.execute(
        """
        UPDATE moderation_actions AS action
        SET case_id = linked.case_id
        FROM (
            SELECT DISTINCT ON (moderation_action_id)
                moderation_action_id,
                case_id
            FROM moderation_case_action_links
            ORDER BY moderation_action_id, linked_at ASC, case_id ASC
        ) AS linked
        WHERE action.id = linked.moderation_action_id
          AND action.case_id IS NULL
        """
    )

    bind = op.get_bind()

    action_rule_rows = bind.execute(
        sa.text(
            """
            SELECT
                action.id AS action_id,
                action.rule_id AS rule_id,
                action.server_id AS server_id,
                rule.code AS rule_code_snapshot,
                rule.title AS rule_title_snapshot,
                action.created_at AS cited_at
            FROM moderation_actions AS action
            JOIN moderation_rules AS rule ON rule.id = action.rule_id
            WHERE action.rule_id IS NOT NULL
            """
        )
    ).mappings().all()

    if action_rule_rows:
        action_rules_table = sa.table(
            "moderation_action_rules",
            sa.column("id", sa.Uuid()),
            sa.column("action_id", sa.Uuid()),
            sa.column("rule_id", sa.Uuid()),
            sa.column("server_id", sa.BigInteger()),
            sa.column("rule_code_snapshot", sa.String()),
            sa.column("rule_title_snapshot", sa.String()),
            sa.column("cited_at", sa.DateTime()),
            sa.column("rule_deleted_at", sa.DateTime()),
        )
        op.bulk_insert(
            action_rules_table,
            [
                {
                    "id": uuid.uuid4(),
                    "action_id": row["action_id"],
                    "rule_id": row["rule_id"],
                    "server_id": row["server_id"],
                    "rule_code_snapshot": row["rule_code_snapshot"],
                    "rule_title_snapshot": row["rule_title_snapshot"],
                    "cited_at": row["cited_at"],
                    "rule_deleted_at": None,
                }
                for row in action_rule_rows
            ],
        )

    case_rule_rows = bind.execute(
        sa.text(
            """
            SELECT
                source.case_id AS case_id,
                source.server_id AS server_id,
                source.rule_id AS rule_id,
                source.rule_code_snapshot AS rule_code_snapshot,
                source.rule_title_snapshot AS rule_title_snapshot,
                MIN(source.cited_at) AS cited_at
            FROM (
                SELECT
                    action.case_id AS case_id,
                    action.server_id AS server_id,
                    action.rule_id AS rule_id,
                    rule.code AS rule_code_snapshot,
                    rule.title AS rule_title_snapshot,
                    action.created_at AS cited_at
                FROM moderation_actions AS action
                JOIN moderation_rules AS rule ON rule.id = action.rule_id
                WHERE action.case_id IS NOT NULL
                  AND action.rule_id IS NOT NULL

                UNION ALL

                SELECT
                    link.case_id AS case_id,
                    action.server_id AS server_id,
                    action.rule_id AS rule_id,
                    rule.code AS rule_code_snapshot,
                    rule.title AS rule_title_snapshot,
                    link.linked_at AS cited_at
                FROM moderation_case_action_links AS link
                JOIN moderation_actions AS action ON action.id = link.moderation_action_id
                JOIN moderation_rules AS rule ON rule.id = action.rule_id
                WHERE action.rule_id IS NOT NULL
            ) AS source
            GROUP BY
                source.case_id,
                source.server_id,
                source.rule_id,
                source.rule_code_snapshot,
                source.rule_title_snapshot
            """
        )
    ).mappings().all()

    if case_rule_rows:
        case_rules_table = sa.table(
            "moderation_case_rules",
            sa.column("id", sa.Uuid()),
            sa.column("case_id", sa.Uuid()),
            sa.column("rule_id", sa.Uuid()),
            sa.column("server_id", sa.BigInteger()),
            sa.column("rule_code_snapshot", sa.String()),
            sa.column("rule_title_snapshot", sa.String()),
            sa.column("cited_at", sa.DateTime()),
            sa.column("rule_deleted_at", sa.DateTime()),
        )
        op.bulk_insert(
            case_rules_table,
            [
                {
                    "id": uuid.uuid4(),
                    "case_id": row["case_id"],
                    "rule_id": row["rule_id"],
                    "server_id": row["server_id"],
                    "rule_code_snapshot": row["rule_code_snapshot"],
                    "rule_title_snapshot": row["rule_title_snapshot"],
                    "cited_at": row["cited_at"],
                    "rule_deleted_at": None,
                }
                for row in case_rule_rows
            ],
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_moderation_rules_before_delete_citation_cleanup ON moderation_rules")
    op.execute("DROP FUNCTION IF EXISTS moderation_rules_before_delete_citation_cleanup")

    op.drop_index("ix_moderation_case_rules_server_id", table_name="moderation_case_rules")
    op.drop_index("ix_moderation_case_rules_rule_id", table_name="moderation_case_rules")
    op.drop_index("ix_moderation_case_rules_case_id", table_name="moderation_case_rules")
    op.drop_table("moderation_case_rules")

    op.drop_index("ix_moderation_action_rules_server_id", table_name="moderation_action_rules")
    op.drop_index("ix_moderation_action_rules_rule_id", table_name="moderation_action_rules")
    op.drop_index("ix_moderation_action_rules_action_id", table_name="moderation_action_rules")
    op.drop_table("moderation_action_rules")

    op.drop_constraint("fk_moderation_actions_case_id_moderation_cases", "moderation_actions", type_="foreignkey")
    op.drop_index("ix_moderation_actions_case_id", table_name="moderation_actions")
    op.drop_column("moderation_actions", "case_id")

    op.alter_column("moderation_case_notes", "author_user_id", existing_type=sa.BigInteger(), nullable=False)
