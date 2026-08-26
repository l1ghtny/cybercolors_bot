"""Add product release note 2026-08-26-moderation-reasons-and-private-commentary.

Revision ID: 6c05781d8aa9
Revises: 99096806a8ad
Create Date: 2026-08-26T20:45:13.409829+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '6c05781d8aa9'
down_revision = '99096806a8ad'
branch_labels = None
depends_on = None


NOTE_ID = '2026-08-26-moderation-reasons-and-private-commentary'


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
                20, 45, 13,
                tzinfo=timezone.utc,
            ),
            title_en='Moderation notices separate reasons from private commentary',
            title_ru='Причины действий отделены от закрытых комментариев',
            summary_en='Members now receive the action reason, while moderator commentary stays in moderation logs and the dashboard.',
            summary_ru='Пользователь теперь получает причину действия, а комментарий модератора остаётся только в журнале и панели управления.',
            change_type='fixed',
            surface='both',
            feature_en='Moderation · Create action',
            feature_ru='Модерация · Создание действия',
            action_label_en='Open moderation',
            action_label_ru='Открыть модерацию',
            action_path='/dashboard/{server_id}/moderation?tab=actions',
            changes=sa.cast(
                op.inline_literal('[{"en": "Action forms clearly separate the member-facing reason from private commentary and remain usable when message cleanup is expanded.", "ru": "В формах создания действия причина для пользователя отделена от закрытого комментария, а выбор удаляемых сообщений больше не растягивает окно за пределы экрана."}]', type_=sa.Text()),
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
