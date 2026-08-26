"""Add product release note 2026-08-26-preserve-moderation-action-reasons.

Revision ID: 99096806a8ad
Revises: d1764e624c51
Create Date: 2026-08-26T18:47:39.254526+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '99096806a8ad'
down_revision = 'd1764e624c51'
branch_labels = None
depends_on = None


NOTE_ID = '2026-08-26-preserve-moderation-action-reasons'


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
                2026, 8, 26,
                18, 47, 38,
                tzinfo=timezone.utc,
            ),
            title_en='Action reasons are saved with cited rules',
            title_ru='Причины действий сохраняются вместе с правилами',
            summary_en='Selecting a rule no longer replaces the reason entered by the moderator when an action is created.',
            summary_ru='Выбранное правило больше не заменяет причину, которую модератор указал при создании действия.',
            change_type='fixed',
            surface='dashboard',
            feature_en='Moderation · Actions',
            feature_ru='Модерация · Действия',
            action_label_en='Open moderation',
            action_label_ru='Открыть модерацию',
            action_path='/dashboard/{server_id}/moderation',
            changes=sa.cast(
                op.inline_literal('[{"en": "Moderation history now shows the moderator’s reason while keeping cited rules in their dedicated section.", "ru": "В журнале модерации теперь отображается причина модератора, а выбранные правила по-прежнему сохраняются отдельно."}]', type_=sa.Text()),
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
