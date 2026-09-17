"""Add product release note 2026-09-17-continuous-service-status-refresh.

Revision ID: 62e3cc4380b8
Revises: 8a8d15d03a5c
Create Date: 2026-09-17T11:36:39.354491+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '62e3cc4380b8'
down_revision = '8a8d15d03a5c'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-17-continuous-service-status-refresh'


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
                2026, 9, 17,
                11, 30, 0,
                tzinfo=timezone.utc,
            ),
            title_en='Service status refreshes without reloading the page',
            title_ru='Состояние бота обновляется без перезагрузки страницы',
            summary_en='Status checks continue while you use another tab. If a check stalls, the dashboard tries again automatically.',
            summary_ru='Проверка состояния бота продолжается, пока вы работаете на другой вкладке. Если запрос зависнет, панель автоматически повторит проверку.',
            change_type='fixed',
            surface='dashboard',
            feature_en='Dashboard · Service status',
            feature_ru='Панель управления · Состояние сервисов',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Returning to the dashboard triggers a fresh check; unavailable or expired reports still show an unknown status.", "ru": "При возвращении на вкладку панель запрашивает свежие данные. Если данные недоступны или устарели, состояние по-прежнему отображается как неизвестное."}]', type_=sa.Text()),
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
