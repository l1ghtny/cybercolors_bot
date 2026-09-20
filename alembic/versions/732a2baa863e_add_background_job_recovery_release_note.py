"""Add product release note 2026-09-20-background-job-recovery.

Revision ID: 732a2baa863e
Revises: 394d5143bacf
Create Date: 2026-09-20T11:38:48.916176+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '732a2baa863e'
down_revision = '394d5143bacf'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-20-background-job-recovery'


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
                2026, 9, 20,
                11, 38, 48,
                tzinfo=timezone.utc,
            ),
            title_en='Background tasks recover after temporary failures',
            title_ru='Фоновые задачи восстанавливаются после временных сбоев',
            summary_en='Temporary database failures no longer leave automatic unmuting and unbanning stopped until the bot restarts. Service status now shows Discord connectivity separately from server configuration sync.',
            summary_ru='После временного сбоя базы данных автоматическое снятие мутов и банов возобновляется без перезапуска бота. В состоянии сервисов подключение к Discord теперь показано отдельно от синхронизации настроек сервера.',
            change_type='fixed',
            surface='both',
            feature_en='Service status · Automatic moderation expiry',
            feature_ru='Состояние сервисов · Автоматическое снятие наказаний',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Stopped background tasks restart automatically; scheduled birthday tasks resume at their next scheduled run.", "ru": "Остановившиеся фоновые задачи запускаются снова; задачи дней рождения продолжают работу при следующем запуске по расписанию."}, {"en": "A service stays marked unavailable until its failed task completes successfully.", "ru": "Сервис остаётся недоступным в индикаторе, пока завершившаяся с ошибкой задача не выполнится успешно."}]', type_=sa.Text()),
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
