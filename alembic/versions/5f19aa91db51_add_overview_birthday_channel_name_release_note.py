"""Add product release note 2026-09-16-overview-birthday-channel-name.

Revision ID: 5f19aa91db51
Revises: a71c293dd420
Create Date: 2026-09-16T13:23:37.184006+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '5f19aa91db51'
down_revision = 'a71c293dd420'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-16-overview-birthday-channel-name'


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
                13, 23, 36,
                tzinfo=timezone.utc,
            ),
            title_en='Birthday channel shown by name',
            title_ru='Название канала поздравлений в обзоре сервера',
            summary_en='The server overview now looks up the birthday channel name in Discord, so you can recognize it even when its name was never saved or has changed.',
            summary_ru='В обзоре сервера теперь отображается название канала поздравлений из Discord, даже если оно не было сохранено или канал переименовали.',
            change_type='fixed',
            surface='dashboard',
            feature_en='Server overview · Birthday channel',
            feature_ru='Обзор сервера · Канал поздравлений',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "If Discord is unavailable, the overview keeps showing the saved name or channel ID.", "ru": "Если Discord недоступен, в обзоре остаётся сохранённое название или ID канала."}]', type_=sa.Text()),
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
