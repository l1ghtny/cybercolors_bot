"""Add server RBAC tables.

Revision ID: b8c9d0e1f2a3
Revises: b6c7d8e9f012, c9d0e1f2a3b4
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = ("b6c7d8e9f012", "c9d0e1f2a3b4")
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        constraint["name"] == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if not _table_exists("server_rbac_assignments"):
        op.create_table(
            "server_rbac_assignments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("subject_type", sa.String(length=20), nullable=False),
            sa.Column("subject_id", sa.String(length=64), nullable=False),
            sa.Column("preset", sa.String(length=50), nullable=True),
            sa.Column("permission_keys", sa.JSON(), nullable=False),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
            sa.Column("updated_by_user_id", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["global_users.discord_id"]),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["global_users.discord_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("server_id", "subject_type", "subject_id", name="uq_server_rbac_assignments_subject"),
        )
    elif not _unique_constraint_exists("server_rbac_assignments", "uq_server_rbac_assignments_subject"):
        op.create_unique_constraint(
            "uq_server_rbac_assignments_subject",
            "server_rbac_assignments",
            ["server_id", "subject_type", "subject_id"],
        )
    _create_index_if_missing("ix_server_rbac_assignments_server_id", "server_rbac_assignments", ["server_id"])
    _create_index_if_missing("ix_server_rbac_assignments_subject_id", "server_rbac_assignments", ["subject_id"])
    _create_index_if_missing("ix_server_rbac_assignments_subject_type", "server_rbac_assignments", ["subject_type"])

    if not _table_exists("server_rbac_audit_events"):
        op.create_table(
            "server_rbac_audit_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("server_id", sa.BigInteger(), nullable=False),
            sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
            sa.Column("subject_type", sa.String(length=20), nullable=False),
            sa.Column("subject_id", sa.String(length=64), nullable=False),
            sa.Column("before_json", sa.JSON(), nullable=True),
            sa.Column("after_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["global_users.discord_id"]),
            sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_server_rbac_audit_events_actor_user_id", "server_rbac_audit_events", ["actor_user_id"])
    _create_index_if_missing("ix_server_rbac_audit_events_created_at", "server_rbac_audit_events", ["created_at"])
    _create_index_if_missing("ix_server_rbac_audit_events_server_id", "server_rbac_audit_events", ["server_id"])
    _create_index_if_missing("ix_server_rbac_audit_events_subject_id", "server_rbac_audit_events", ["subject_id"])
    _create_index_if_missing("ix_server_rbac_audit_events_subject_type", "server_rbac_audit_events", ["subject_type"])


def downgrade() -> None:
    _drop_index_if_exists("ix_server_rbac_audit_events_subject_type", "server_rbac_audit_events")
    _drop_index_if_exists("ix_server_rbac_audit_events_subject_id", "server_rbac_audit_events")
    _drop_index_if_exists("ix_server_rbac_audit_events_server_id", "server_rbac_audit_events")
    _drop_index_if_exists("ix_server_rbac_audit_events_created_at", "server_rbac_audit_events")
    _drop_index_if_exists("ix_server_rbac_audit_events_actor_user_id", "server_rbac_audit_events")
    if _table_exists("server_rbac_audit_events"):
        op.drop_table("server_rbac_audit_events")

    _drop_index_if_exists("ix_server_rbac_assignments_subject_type", "server_rbac_assignments")
    _drop_index_if_exists("ix_server_rbac_assignments_subject_id", "server_rbac_assignments")
    _drop_index_if_exists("ix_server_rbac_assignments_server_id", "server_rbac_assignments")
    if _table_exists("server_rbac_assignments"):
        op.drop_table("server_rbac_assignments")
