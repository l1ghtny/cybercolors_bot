"""Add product release note 2026-08-16-least-active-member-ranking.

Revision ID: 99a9a23614b3
Revises: d8f3a7c1e624
Create Date: 2026-08-16T15:35:40.996422+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '99a9a23614b3'
down_revision = 'd8f3a7c1e624'
branch_labels = None
depends_on = None


NOTE_ID = '2026-08-16-least-active-member-ranking'


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
                2026, 8, 16,
                15, 35, 40,
                tzinfo=timezone.utc,
            ),
            title_en='Accurate least-active member rankings',
            title_ru='Точный рейтинг наименее активных участников',
            summary_en='The bot can now rank members by the fewest messages in a selected period instead of reversing a limited most-active list.',
            summary_ru='Бот теперь ранжирует участников по наименьшему числу сообщений за выбранный период, а не переворачивает сокращённый список самых активных.',
            change_type='fixed',
            surface='bot',
            feature_en='AI assistant · Member activity',
            feature_ru='ИИ-помощник · Активность участников',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Ask for the least active members over a date range to get a correctly ordered result among members who posted during that period.", "ru": "Можно запросить наименее активных участников за нужный период и получить корректный рейтинг среди тех, кто писал в это время."}]', type_=sa.Text()),
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
