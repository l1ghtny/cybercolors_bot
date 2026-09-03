"""Add product release note 2026-09-03-readable-member-profile-layout.

Revision ID: d8b649708586
Revises: a3d7e9f1b5c2
Create Date: 2026-09-03T12:06:29.515678+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'd8b649708586'
down_revision = 'a3d7e9f1b5c2'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-03-readable-member-profile-layout'


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
                2026, 9, 3,
                12, 6, 29,
                tzinfo=timezone.utc,
            ),
            title_en='Member profiles stay readable in narrower windows',
            title_ru='Профили участников удобно читать даже в узких окнах',
            summary_en='The profile header now keeps identity details, moderation shortcuts, and summary counts readable when the dashboard has limited horizontal space.',
            summary_ru='Шапка профиля остаётся читаемой, даже когда панели не хватает места по ширине: данные участника, быстрые действия и счётчики больше не сжимают друг друга.',
            change_type='fixed',
            surface='dashboard',
            feature_en='Members · Member profile',
            feature_ru='Участники · Профиль участника',
            action_label_en='Open members',
            action_label_ru='Открыть участников',
            action_path='/dashboard/{server_id}/users',
            changes=sa.cast(
                op.inline_literal('[{"en": "Summary cards move below member details at narrower desktop widths, preventing usernames and Discord IDs from collapsing into vertical text.", "ru": "При небольшой ширине экрана счётчики переходят под данные участника, поэтому имя и Discord ID больше не разбиваются по одному символу."}, {"en": "The note-removal dialog now shows a translated Cancel action and exposes its explanation correctly to assistive technology.", "ru": "В окне удаления заметки кнопка отмены переведена, а пояснение корректно доступно скринридерам."}]', type_=sa.Text()),
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
