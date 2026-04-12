import uuid
from collections import OrderedDict

import sqlalchemy as sa
from alembic import op

"""normalize replies to one-to-many triggers

Revision ID: d9b8a8e6ef7f
Revises: a2d55f38cf11
Create Date: 2026-04-12 08:15:00.000000

"""


# revision identifiers, used by Alembic.
revision = "d9b8a8e6ef7f"
down_revision = "a2d55f38cf11"
branch_labels = None
depends_on = None


def _group_key(row: dict[str, object]) -> tuple[object, object]:
    return row["server_id"], row["bot_reply"]


def upgrade() -> None:
    bind = op.get_bind()

    old_reply_count = bind.execute(sa.text("SELECT COUNT(*) FROM replies")).scalar_one()
    source_rows = bind.execute(
        sa.text(
            """
            SELECT
                r.id,
                r.bot_reply,
                r.server_id,
                r.created_at,
                r.created_by_id,
                t.message
            FROM replies AS r
            JOIN triggers AS t
                ON t.id = r.user_message
            ORDER BY r.created_at ASC, r.id ASC
            """
        )
    ).mappings().all()

    if len(source_rows) != old_reply_count:
        raise RuntimeError(
            f"Migration aborted: expected {old_reply_count} joined rows from replies/triggers, got {len(source_rows)}."
        )

    canonical_replies: "OrderedDict[tuple[object, object], dict[str, object]]" = OrderedDict()
    trigger_pairs: set[tuple[object, object]] = set()

    for row in source_rows:
        row_dict = dict(row)
        key = _group_key(row_dict)
        if key not in canonical_replies:
            canonical_replies[key] = {
                "id": row_dict["id"],
                "bot_reply": row_dict["bot_reply"],
                "server_id": row_dict["server_id"],
                "created_at": row_dict["created_at"],
                "created_by_id": row_dict["created_by_id"],
            }
        trigger_pairs.add((canonical_replies[key]["id"], row_dict["message"]))

    op.create_table(
        "replies_new",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_reply", sa.String(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "triggers_new",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("reply_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["reply_id"], ["replies_new.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    replies_new = sa.table(
        "replies_new",
        sa.column("id", sa.Uuid()),
        sa.column("bot_reply", sa.String()),
        sa.column("server_id", sa.BigInteger()),
        sa.column("created_at", sa.DateTime()),
        sa.column("created_by_id", sa.BigInteger()),
    )
    triggers_new = sa.table(
        "triggers_new",
        sa.column("id", sa.Uuid()),
        sa.column("message", sa.String()),
        sa.column("reply_id", sa.Uuid()),
    )

    if canonical_replies:
        op.bulk_insert(replies_new, list(canonical_replies.values()))
    if trigger_pairs:
        trigger_rows = [
            {"id": uuid.uuid4(), "message": message, "reply_id": reply_id}
            for reply_id, message in sorted(trigger_pairs, key=lambda item: (str(item[0]), item[1]))
        ]
        op.bulk_insert(triggers_new, trigger_rows)

    new_trigger_count = bind.execute(sa.text("SELECT COUNT(*) FROM triggers_new")).scalar_one()
    if old_reply_count > 0 and new_trigger_count == 0:
        raise RuntimeError("Migration aborted: no triggers were migrated into normalized tables.")

    op.drop_constraint("fk_replies_user_message", "replies", type_="foreignkey")
    op.drop_index(op.f("ix_replies_bot_reply"), table_name="replies")
    op.drop_table("replies")
    op.drop_table("triggers")

    op.rename_table("replies_new", "replies")
    op.rename_table("triggers_new", "triggers")

    op.create_index(op.f("ix_replies_bot_reply"), "replies", ["bot_reply"], unique=False)
    op.create_index(op.f("ix_triggers_message"), "triggers", ["message"], unique=False)
    op.create_unique_constraint("uq_triggers_reply_message", "triggers", ["reply_id", "message"])


def downgrade() -> None:
    bind = op.get_bind()

    source_rows = bind.execute(
        sa.text(
            """
            SELECT
                r.bot_reply,
                r.server_id,
                r.created_at,
                r.created_by_id,
                t.message
            FROM replies AS r
            JOIN triggers AS t
                ON t.reply_id = r.id
            ORDER BY r.created_at ASC
            """
        )
    ).mappings().all()

    trigger_message_to_id: dict[str, uuid.UUID] = {}
    for row in source_rows:
        message = row["message"]
        if message not in trigger_message_to_id:
            trigger_message_to_id[message] = uuid.uuid4()

    op.create_table(
        "triggers_old",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "replies_old",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_message", sa.Uuid(), nullable=False),
        sa.Column("bot_reply", sa.String(), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["global_users.discord_id"]),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"]),
        sa.ForeignKeyConstraint(["user_message"], ["triggers_old.id"], name="fk_replies_user_message"),
        sa.PrimaryKeyConstraint("id"),
    )

    triggers_old = sa.table(
        "triggers_old",
        sa.column("id", sa.Uuid()),
        sa.column("message", sa.String()),
    )
    replies_old = sa.table(
        "replies_old",
        sa.column("id", sa.Uuid()),
        sa.column("user_message", sa.Uuid()),
        sa.column("bot_reply", sa.String()),
        sa.column("server_id", sa.BigInteger()),
        sa.column("created_at", sa.DateTime()),
        sa.column("created_by_id", sa.BigInteger()),
    )

    if trigger_message_to_id:
        op.bulk_insert(
            triggers_old,
            [{"id": trigger_id, "message": message} for message, trigger_id in trigger_message_to_id.items()],
        )

    if source_rows:
        op.bulk_insert(
            replies_old,
            [
                {
                    "id": uuid.uuid4(),
                    "user_message": trigger_message_to_id[row["message"]],
                    "bot_reply": row["bot_reply"],
                    "server_id": row["server_id"],
                    "created_at": row["created_at"],
                    "created_by_id": row["created_by_id"],
                }
                for row in source_rows
            ],
        )

    op.drop_constraint("uq_triggers_reply_message", "triggers", type_="unique")
    op.drop_index(op.f("ix_triggers_message"), table_name="triggers")
    op.drop_index(op.f("ix_replies_bot_reply"), table_name="replies")
    op.drop_table("triggers")
    op.drop_table("replies")

    op.rename_table("triggers_old", "triggers")
    op.rename_table("replies_old", "replies")

    op.create_index(op.f("ix_replies_bot_reply"), "replies", ["bot_reply"], unique=False)
