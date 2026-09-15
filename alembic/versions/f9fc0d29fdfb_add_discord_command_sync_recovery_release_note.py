"""Add product release note 2026-09-15-discord-command-sync-recovery.

Revision ID: f9fc0d29fdfb
Revises: 522182b8f89e
Create Date: 2026-09-15T15:25:06.144065+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'f9fc0d29fdfb'
down_revision = '522182b8f89e'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-15-discord-command-sync-recovery'


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
                2026, 9, 15,
                15, 25, 5,
                tzinfo=timezone.utc,
            ),
            title_en='Background tasks resume when Discord reconnects',
            title_ru='Фоновые задачи запускаются после переподключения к Discord',
            summary_en='Temporary errors while registering Discord commands no longer prevent automatic unmuting and birthday tasks from starting after the bot reconnects.',
            summary_ru='Временные ошибки при регистрации команд Discord больше не мешают запуску автоматического снятия мутов и задач дней рождения после переподключения бота.',
            change_type='fixed',
            surface='bot',
            feature_en='Bot · Recovery after Discord outages',
            feature_ru='Бот · Восстановление после сбоев Discord',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Command registration retries automatically while other startup tasks continue.", "ru": "Бот повторяет регистрацию команд, не задерживая запуск остальных задач."}]', type_=sa.Text()),
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
