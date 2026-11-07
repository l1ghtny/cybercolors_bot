"""Add product release note 2026-11-07-activity-custom-dates.

Revision ID: eb3ca5db69a9
Revises: 2dc722d70731
Create Date: 2026-11-07T11:29:59.338007+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'eb3ca5db69a9'
down_revision = '2dc722d70731'
branch_labels = None
depends_on = None


NOTE_ID = '2026-11-07-activity-custom-dates'


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
    table = _release_notes_table()
    op.get_bind().execute(
        table.insert().values(
            id=NOTE_ID,
            published_at=datetime(
                2026, 11, 7,
                11, 29, 59,
                tzinfo=timezone.utc,
            ),
            title_en='Custom date ranges work in Activity',
            title_ru='В «Активности» снова можно выбрать свой период',
            summary_en='The activity leaderboard now keeps the dates you pick and counts messages within the selected period.',
            summary_ru='Выбранные даты сохраняются, а в рейтинге активности учитываются сообщения за этот период.',
            change_type='fixed',
            surface='dashboard',
            feature_en='Members · Activity',
            feature_ru='Участники · Активность',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Set a start date, an end date, or both to filter the leaderboard.", "ru": "Чтобы отфильтровать рейтинг, укажите начальную дату, конечную дату или обе."}]', type_=sa.Text()),
                sa.JSON(),
            ),
            is_published=True,
            is_public=False,
            public_slug=None,
            public_title_en=None,
            public_title_ru=None,
            public_summary_en=None,
            public_summary_ru=None,
            public_action_label_en=None,
            public_action_label_ru=None,
            public_action_url=None,
            public_image_url=None,
        )
    )


def downgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))
