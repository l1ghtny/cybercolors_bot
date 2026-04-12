import uuid

import sqlalchemy as sa
from alembic import op

"""normalize reply triggers

Revision ID: a2d55f38cf11
Revises: messages_removed
Create Date: 2026-04-12 07:40:00.000000

"""


# revision identifiers, used by Alembic.
revision = "a2d55f38cf11"
down_revision = "messages_removed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "triggers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    bind = op.get_bind()
    replies = sa.table(
        "replies",
        sa.column("user_message", sa.String()),
    )
    triggers = sa.table(
        "triggers",
        sa.column("id", sa.Uuid()),
        sa.column("message", sa.String()),
    )

    distinct_messages = bind.execute(
        sa.select(sa.distinct(replies.c.user_message)).where(replies.c.user_message.is_not(None))
    )

    batch: list[dict[str, object]] = []
    for (message,) in distinct_messages:
        batch.append({"id": uuid.uuid4(), "message": message})
        if len(batch) >= 1000:
            op.bulk_insert(triggers, batch)
            batch.clear()
    if batch:
        op.bulk_insert(triggers, batch)

    op.add_column("replies", sa.Column("user_message_id", sa.Uuid(), nullable=True))
    bind.execute(
        sa.text(
            """
            UPDATE replies
            SET user_message_id = (
                SELECT t.id
                FROM triggers AS t
                WHERE t.message = replies.user_message
            )
            """
        )
    )

    unmapped_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM replies
            WHERE user_message IS NOT NULL
              AND user_message_id IS NULL
            """
        )
    ).scalar_one()
    if unmapped_count:
        raise RuntimeError(f"Migration aborted: {unmapped_count} replies were not mapped to triggers.")

    op.drop_column("replies", "user_message")
    op.alter_column(
        "replies",
        "user_message_id",
        new_column_name="user_message",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_replies_user_message",
        "replies",
        "triggers",
        ["user_message"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_replies_user_message", "replies", type_="foreignkey")
    op.add_column("replies", sa.Column("user_message_text", sa.String(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE replies
            SET user_message_text = t.message
            FROM triggers AS t
            WHERE replies.user_message = t.id
            """
        )
    )

    missing_text_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM replies
            WHERE user_message IS NOT NULL
              AND user_message_text IS NULL
            """
        )
    ).scalar_one()
    if missing_text_count:
        raise RuntimeError(
            f"Downgrade aborted: {missing_text_count} replies could not be remapped to text triggers."
        )

    op.drop_column("replies", "user_message")
    op.alter_column(
        "replies",
        "user_message_text",
        new_column_name="user_message",
        existing_type=sa.String(),
        nullable=False,
    )
    op.drop_table("triggers")
