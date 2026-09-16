"""Add product release note 2026-09-16-service-status-device-clock.

Revision ID: 8a8d15d03a5c
Revises: 5f19aa91db51
Create Date: 2026-09-16T13:30:20.929073+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '8a8d15d03a5c'
down_revision = '5f19aa91db51'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-16-service-status-device-clock'


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
                2026, 9, 16,
                13, 30, 0,
                tzinfo=timezone.utc,
            ),
            title_en='Service status works with an incorrect device clock',
            title_ru='Состояние бота не зависит от часов на устройстве',
            summary_en='A device clock that runs ahead or behind no longer makes a healthy bot appear as “Status unknown”. Stale reports still expire.',
            summary_ru='Если часы на устройстве спешат или отстают, исправно работающий бот больше не отображается с неизвестным состоянием. Устаревшие данные по-прежнему не считаются актуальными.',
            change_type='fixed',
            surface='dashboard',
            feature_en='Dashboard · Service status',
            feature_ru='Панель управления · Состояние сервисов',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Returning to the dashboard refreshes the status before showing the bot as healthy.", "ru": "При возвращении на вкладку панель запрашивает свежие данные, прежде чем показать, что бот работает."}]', type_=sa.Text()),
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
