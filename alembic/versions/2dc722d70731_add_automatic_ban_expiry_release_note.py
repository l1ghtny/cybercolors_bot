"""Add product release note 2026-10-01-automatic-ban-expiry.

Revision ID: 2dc722d70731
Revises: 732a2baa863e
Create Date: 2026-10-01T08:42:37.890333+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '2dc722d70731'
down_revision = '732a2baa863e'
branch_labels = None
depends_on = None


NOTE_ID = '2026-10-01-automatic-ban-expiry'


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
                2026, 10, 1,
                8, 42, 37,
                tzinfo=timezone.utc,
            ),
            title_en='Temporary bans expire without stopping moderation tasks',
            title_ru='Временные баны снимаются без сбоев фоновой модерации',
            summary_en='Fixed an error when logging an expired ban that could stop automatic expiry and leave the bot marked unhealthy.',
            summary_ru='Исправлена ошибка при записи снятого бана в журнал модерации. Из-за неё автоматическое снятие наказаний прерывалось, а бот отображался как недоступный.',
            change_type='fixed',
            surface='both',
            feature_en='Moderation · Temporary bans',
            feature_ru='Модерация · Временные баны',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Expired bans are closed in the action history, and moderation log entries show the original action number.", "ru": "Баны с истёкшим сроком закрываются в истории наказаний, а запись в журнале модерации содержит номер исходного действия."}, {"en": "If a ban was already lifted in Discord, its expired action is still closed in the dashboard.", "ru": "Если бан уже снят в Discord, действие с истёкшим сроком всё равно закрывается в панели управления."}]', type_=sa.Text()),
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
