"""Add product release note 2026-09-04-youtube-audio-download-compatibility.

Revision ID: 49703b66f5d6
Revises: d8b649708586
Create Date: 2026-09-04T08:49:35.878362+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '49703b66f5d6'
down_revision = 'd8b649708586'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-04-youtube-audio-download-compatibility'


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
                2026, 9, 4,
                8, 49, 35,
                tzinfo=timezone.utc,
            ),
            title_en='Fixed YouTube audio download failures',
            title_ru='Исправлена ошибка загрузки аудио с YouTube',
            summary_en='Updated YouTube imports to handle recent changes that prevented some videos from reaching transcription.',
            summary_ru='Обновили импорт с учётом изменений YouTube, из-за которых некоторые видео не доходили до расшифровки.',
            change_type='fixed',
            surface='dashboard',
            feature_en='AI knowledge · YouTube videos',
            feature_ru='База знаний ИИ · Видео YouTube',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Videos without usable captions can download their audio for transcription again.", "ru": "Для видео без подходящих субтитров снова можно скачать аудио для расшифровки."}, {"en": "Retry affected videos using Reindex in the knowledge source list.", "ru": "Для видео с этой ошибкой нажмите «Переиндексировать» в списке источников знаний."}]', type_=sa.Text()),
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
