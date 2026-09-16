"""Persist private bot runtime and external advisory snapshots."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "a71c293dd420"
down_revision = "f9fc0d29fdfb"
branch_labels = None
depends_on = None


NOTE_ID = '2026-09-16-server-service-status'


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



def upgrade():
    op.create_table("bot_runtime_status",
        sa.Column("profile", sa.String(32), primary_key=True),
        sa.Column("process_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table("external_service_status",
        sa.Column("service", sa.String(32), primary_key=True),
        sa.Column("attempted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("incidents", sa.JSON(), nullable=False),
    )

    table = _release_notes_table()
    op.get_bind().execute(
        table.insert().values(
            id=NOTE_ID,
            published_at=datetime(
                2026, 9, 16,
                12, 0, 0,
                tzinfo=timezone.utc,
            ),
            title_en='See the bot’s status for your server',
            title_ru='Состояние бота на вашем сервере',
            summary_en='The dashboard now shows the bot’s connection, command registration, automatic unmuting and unbanning, and birthday task status for the selected server.',
            summary_ru='В панели управления теперь видно состояние подключения бота, регистрации команд, автоматического снятия мутов и банов и задач дней рождения на выбранном сервере.',
            change_type='added',
            surface='dashboard',
            feature_en='Dashboard · Service status',
            feature_ru='Панель управления · Состояние сервисов',
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=sa.cast(
                op.inline_literal('[{"en": "Open the status indicator in the top bar for details. When current data is unavailable, the indicator shows an unknown state. Discord incident notices appear separately.", "ru": "Нажмите на индикатор в верхней панели, чтобы увидеть подробности. Без свежих данных состояние отображается как неизвестное. Сообщения о сбоях Discord показаны отдельно."}]', type_=sa.Text()),
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


def downgrade():
    table = _release_notes_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))
    op.drop_table("external_service_status")
    op.drop_table("bot_runtime_status")
