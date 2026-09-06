"""Add product release note 2026-09-06-youtube-duration-and-indexing.

Revision ID: 522182b8f89e
Revises: e1c7a4b9d620
Create Date: 2026-09-06T06:58:06.707165+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '522182b8f89e'
down_revision = 'e1c7a4b9d620'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-06-youtube-duration-and-indexing'


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
                2026, 9, 6,
                6, 58, 6,
                tzinfo=timezone.utc,
            ),
            title_en='Two-hour YouTube limit and reliable indexing',
            title_ru='Лимит в два часа для YouTube и исправления индексации',
            summary_en='YouTube knowledge imports now accept videos up to two hours long. Large transcripts are indexed in smaller batches, and failed sources show their current error.',
            summary_ru='В базу знаний можно импортировать видео YouTube длительностью до двух часов. Большие расшифровки индексируются небольшими порциями, а при сбое источник показывает актуальную ошибку.',
            change_type='fixed',
            surface='dashboard',
            feature_en='AI · Knowledge base',
            feature_ru='ИИ · База знаний',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Videos over two hours are rejected before audio download or transcription; automatic channel indexing skips them.", "ru": "Видео длиннее двух часов отклоняются до загрузки аудио и расшифровки; автоматическая индексация канала пропускает их."}, {"en": "Large transcripts no longer fail because too many fragments were sent for indexing at once.", "ru": "Большие расшифровки больше не вызывают ошибку из-за отправки слишком большого числа фрагментов за один раз."}, {"en": "Failed indexing updates the source status and replaces stale transcription errors.", "ru": "При сбое индексации обновляются статус источника и сообщение об ошибке; прежняя ошибка расшифровки больше не остаётся на экране."}]', type_=sa.Text()),
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
