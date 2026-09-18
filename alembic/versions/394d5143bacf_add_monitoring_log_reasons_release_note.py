"""Repair identifiable automatic monitoring actors and add a release note.

Revision ID: 394d5143bacf
Revises: 8a8d15d03a5c
Create Date: 2026-09-18T13:26:28.399809+00:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '394d5143bacf'
down_revision = '8a8d15d03a5c'
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-18-monitoring-log-reasons'


def _repair_automatic_actors() -> None:
    # Match the historical writers using both source and their saved trigger.
    # Never infer an old event's reason from the mutable monitoring record.
    op.execute(sa.text(r"""
        UPDATE monitored_user_status_events AS event
        SET changed_by_user_id = NULL
        FROM monitored_users AS monitored
        WHERE monitored.id = event.monitored_user_id
          AND event.changed_by_user_id = monitored.user_id
          AND event.to_is_active IS TRUE
          AND (
            (monitored.source = 'auto'
             AND event.reason ~ ': (account_age_days=[0-9]+(, no_avatar)?|no_avatar)$')
            OR
            (monitored.source = 'newcomer'
             AND event.reason = 'Automatic newcomer probation after rules acknowledgement')
          )
    """))


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
    _repair_automatic_actors()
    table = _release_notes_table()
    op.get_bind().execute(
        table.insert().values(
            id=NOTE_ID,
            published_at=datetime(
                2026, 9, 18,
                13, 26, 27,
                tzinfo=timezone.utc,
            ),
            title_en='Correct reasons and actors in monitoring history',
            title_ru='Исправлены причины и авторы событий наблюдения',
            summary_en='Monitoring history shows the reason saved for each status change. Automatic activation is no longer attributed to the monitored member.',
            summary_ru='В истории наблюдения отображается причина каждого изменения статуса. Автоматическое включение больше не приписывается самому участнику.',
            change_type='fixed',
            surface='both',
            feature_en='Monitoring · Moderation history',
            feature_ru='Наблюдение · История модерации',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Enabling and disabling monitoring retain their own reasons in the server moderation log, even after later edits.", "ru": "В журнале модерации у включения и отключения наблюдения отображаются свои причины, даже после последующих изменений."}, {"en": "New automatic activations are recorded without a human author; manual decisions retain the moderator who made them.", "ru": "Новые автоматические включения записываются без автора. У ручных изменений сохраняется модератор, принявший решение."}]', type_=sa.Text()),
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
    # Keep corrected audit attribution; a downgrade must not invent an actor.
    table = _release_notes_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))
