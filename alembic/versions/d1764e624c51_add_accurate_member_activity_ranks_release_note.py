"""Add product release note 2026-08-16-accurate-member-activity-ranks.

Revision ID: d1764e624c51
Revises: 99a9a23614b3
Create Date: 2026-08-16T18:24:17.343197+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'd1764e624c51'
down_revision = '99a9a23614b3'
branch_labels = None
depends_on = None


NOTE_ID = '2026-08-16-accurate-member-activity-ranks'


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
                2026, 8, 16,
                18, 24, 17,
                tzinfo=timezone.utc,
            ),
            title_en='Activity positions now use the full leaderboard',
            title_ru='Место по активности теперь считается по всему рейтингу',
            summary_en='When a member asks what place they hold, the bot now calculates the position across the full eligible server leaderboard and reports complete stored activity totals.',
            summary_ru='Когда участник спрашивает, какое место занимает по активности, бот теперь считает позицию по всему рейтингу сервера и учитывает всю сохранённую активность.',
            change_type='fixed',
            surface='bot',
            feature_en='AI companion · Member activity',
            feature_ru='ИИ-помощник · Активность участников',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Ranks are calculated before selecting the requested member, activity from archived threads remains included, and imported history no longer duplicates live counts.", "ru": "Сначала бот строит общий рейтинг и только потом находит в нём участника; сообщения из архивных веток учитываются, а импортированная история больше не удваивает текущие данные."}]', type_=sa.Text()),
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
