"""Add shared member notes and monitoring-reason history.

Revision ID: a3d7e9f1b5c2
Revises: 6c05781d8aa9
Create Date: 2026-09-03 11:10:00.000000+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "a3d7e9f1b5c2"
down_revision = "6c05781d8aa9"
branch_labels = None
depends_on = None


NOTE_ID = "2026-09-03-shared-member-notes-history"


def _release_notes_table() -> sa.TableClause:
    return sa.table(
        "product_release_notes",
        sa.column("id", sa.String),
        sa.column("published_at", sa.TIMESTAMP(timezone=True)),
        sa.column("title_en", sa.String),
        sa.column("title_ru", sa.String),
        sa.column("summary_en", sa.Text),
        sa.column("summary_ru", sa.Text),
        sa.column("change_type", sa.String),
        sa.column("surface", sa.String),
        sa.column("feature_en", sa.String),
        sa.column("feature_ru", sa.String),
        sa.column("action_label_en", sa.String),
        sa.column("action_label_ru", sa.String),
        sa.column("action_path", sa.String),
        sa.column("changes", sa.JSON),
        sa.column("is_published", sa.Boolean),
        sa.column("is_public", sa.Boolean),
        sa.column("public_slug", sa.String),
        sa.column("public_title_en", sa.String),
        sa.column("public_title_ru", sa.String),
        sa.column("public_summary_en", sa.Text),
        sa.column("public_summary_ru", sa.Text),
        sa.column("public_action_label_en", sa.String),
        sa.column("public_action_label_ru", sa.String),
        sa.column("public_action_url", sa.String),
        sa.column("public_image_url", sa.String),
    )


def upgrade() -> None:
    op.create_table(
        "member_notes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND note IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND note IS NULL AND deletion_reason IS NOT NULL)",
            name="ck_member_notes_content_lifecycle",
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.server_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["global_users.discord_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["global_users.discord_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["global_users.discord_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_member_notes_server_id", "member_notes", ["server_id"])
    op.create_index("ix_member_notes_user_id", "member_notes", ["user_id"])
    op.create_index("ix_member_notes_created_at", "member_notes", ["created_at"])
    op.create_index("ix_member_notes_deleted_at", "member_notes", ["deleted_at"])
    op.create_index(
        "ix_member_notes_server_user_created",
        "member_notes",
        ["server_id", "user_id", "created_at"],
    )

    op.add_column(
        "monitored_user_status_events",
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.alter_column(
        "monitored_user_status_events",
        "changed_by_user_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    table = _release_notes_table()
    op.get_bind().execute(
        table.insert().values(
            id=NOTE_ID,
            published_at=datetime(2026, 9, 3, 11, 10, tzinfo=timezone.utc),
            title_en="Shared member notes and one moderation timeline",
            title_ru="Общие заметки об участниках и единая история модерации",
            summary_en=(
                "Moderators can record context without starting monitoring or a case, then review notes, "
                "actions, cases, and monitoring changes in one chronological history."
            ),
            summary_ru=(
                "Модераторы могут записать важный контекст, не включая наблюдение и не создавая дело, "
                "а затем увидеть заметки, действия, дела и изменения статуса наблюдения в единой хронологии."
            ),
            change_type="added",
            surface="both",
            feature_en="Members · Notes and moderation history",
            feature_ru="Участники · Заметки и история модерации",
            action_label_en="Open members",
            action_label_ru="Открыть участников",
            action_path="/dashboard/{server_id}/users",
            changes=sa.cast(
                op.inline_literal(
                    """[{"en": "Add private notes directly to a member without opening a case or enabling monitoring; every note keeps its author and timestamp.", "ru": "Добавляйте закрытые заметки прямо в профиль участника — без дела и наблюдения. Для каждой заметки сохраняются автор и время."}, {"en": "Review notes, moderation actions, cases, and monitoring changes together in chronological order in the dashboard or with Discord commands.", "ru": "Смотрите заметки, действия модерации, дела и изменения статуса наблюдения в одной хронологии — в панели управления или через команды Discord."}, {"en": "Monitoring activation and deactivation now retain the reason for each status change.", "ru": "Причина теперь сохраняется отдельно для каждого включения и отключения наблюдения."}]""",
                    type_=sa.Text(),
                ),
                sa.JSON(),
            ),
            is_published=True,
            is_public=True,
            public_slug="shared-member-notes-history",
            public_title_en="Shared moderation memory for every member",
            public_title_ru="Единая история модерации для каждого участника",
            public_summary_en=(
                "Modral gives moderation teams one private timeline for member notes, actions, cases, "
                "and monitoring decisions, so context is available before the next action."
            ),
            public_summary_ru=(
                "Modral собирает заметки, действия, дела и решения о наблюдении в одной закрытой истории, "
                "чтобы перед следующим действием у команды был весь нужный контекст."
            ),
            public_action_label_en=None,
            public_action_label_ru=None,
            public_action_url=None,
            public_image_url=None,
        )
    )


def downgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))
    op.execute(
        """
        UPDATE monitored_user_status_events AS event
        SET changed_by_user_id = monitored.added_by_user_id
        FROM monitored_users AS monitored
        WHERE monitored.id = event.monitored_user_id
          AND event.changed_by_user_id IS NULL
        """
    )
    op.alter_column(
        "monitored_user_status_events",
        "changed_by_user_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.drop_column("monitored_user_status_events", "reason")
    op.drop_index("ix_member_notes_server_user_created", table_name="member_notes")
    op.drop_index("ix_member_notes_deleted_at", table_name="member_notes")
    op.drop_index("ix_member_notes_created_at", table_name="member_notes")
    op.drop_index("ix_member_notes_user_id", table_name="member_notes")
    op.drop_index("ix_member_notes_server_id", table_name="member_notes")
    op.drop_table("member_notes")
