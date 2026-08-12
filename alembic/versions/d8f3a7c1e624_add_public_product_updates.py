"""Add curated public product updates.

Revision ID: d8f3a7c1e624
Revises: a6e4c2f8b913
Create Date: 2026-08-12 08:40:53.000000
"""

from datetime import datetime, timezone
import json

from alembic import op
import sqlalchemy as sa


revision = "d8f3a7c1e624"
down_revision = "a6e4c2f8b913"
branch_labels = None
depends_on = None


NOTE_ID = "2026-08-12-public-product-updates"


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


def _json_literal(value: list[dict[str, str]]) -> sa.ColumnElement:
    return sa.cast(
        op.inline_literal(
            json.dumps(value, ensure_ascii=False),
            type_=sa.Text(),
        ),
        sa.JSON(),
    )


PUBLIC_UPDATES = (
    {
        "id": "2026-08-06-warns-command",
        "slug": "members-can-review-active-warnings",
        "title_en": "Members can review their active warnings",
        "title_ru": "Участники могут посмотреть свои активные предупреждения",
        "summary_en": (
            "The /warns command gives members a clear, private view of their "
            "current warnings and the reasons behind them."
        ),
        "summary_ru": (
            "Команда /warns показывает участнику его действующие предупреждения "
            "и причины, по которым они были выданы. Ответ видит только сам участник."
        ),
        "action_label_en": "Open the command reference",
        "action_label_ru": "Открыть справочник команд",
        "action_url": "/docs/reference/command-reference",
    },
    {
        "id": "2026-08-02-scheduled-posts-v2",
        "slug": "scheduled-discord-posts",
        "title_en": "Schedule Discord posts and track every delivery",
        "title_ru": "Планируйте публикации в Discord и следите за отправкой",
        "summary_en": (
            "Teams can prepare one-time or recurring posts, attach files, review "
            "the next delivery, and see whether each run succeeded."
        ),
        "summary_ru": (
            "Команда может заранее подготовить разовую или регулярную публикацию, "
            "приложить файлы, проверить время отправки и посмотреть результат каждого запуска."
        ),
        "action_label_en": "Read about scheduled posts",
        "action_label_ru": "Подробнее о публикациях по расписанию",
        "action_url": "/docs/community/scheduled-posts",
    },
    {
        "id": "2026-07-26-intent-replies-v2",
        "slug": "meaning-based-automatic-replies",
        "title_en": "Automatic replies can match meaning, not only exact words",
        "title_ru": "Автоответы распознают смысл, а не только точные фразы",
        "summary_en": (
            "Create focused reply intents, provide examples when AI variation is "
            "useful, and keep deterministic triggers for the cases that need them."
        ),
        "summary_ru": (
            "Для автоответа можно задать отдельный сценарий, добавить примеры для "
            "ИИ и при необходимости оставить точные фразы-триггеры."
        ),
        "action_label_en": "Explore automatic replies",
        "action_label_ru": "Подробнее об автоответах",
        "action_url": "/docs/community/replies-and-birthdays",
    },
    {
        "id": "2026-07-26-command-visibility-v2",
        "slug": "discord-command-access",
        "title_en": "Manage Discord command access from one place",
        "title_ru": "Управляйте доступом к командам Discord в одном месте",
        "summary_en": (
            "Server teams can see who may use each command and align Discord "
            "command visibility with dashboard permissions before rollout."
        ),
        "summary_ru": (
            "Команда сервера видит, кому доступна каждая команда, и может заранее "
            "согласовать права в Discord с правами в панели."
        ),
        "action_label_en": "Read about command access",
        "action_label_ru": "Подробнее о доступе к командам",
        "action_url": "/docs/team/discord-command-access",
    },
    {
        "id": "2026-07-17-private-case-evidence-v2",
        "slug": "private-moderation-case-evidence",
        "title_en": "Keep case evidence private and connected to the decision",
        "title_ru": "Храните закрытые доказательства вместе с делом",
        "summary_en": (
            "Moderators can attach screenshots, files, and links to a case without "
            "moving sensitive evidence into a public Discord channel."
        ),
        "summary_ru": (
            "Модераторы могут приложить к делу скриншоты, файлы и ссылки, не "
            "публикуя закрытые материалы в общем канале Discord."
        ),
        "action_label_en": "See cases and evidence",
        "action_label_ru": "Подробнее о делах и доказательствах",
        "action_url": "/docs/moderation/cases-and-evidence",
    },
    {
        "id": "2026-07-17-bulk-ai-review-v2",
        "slug": "batch-ai-moderation-review",
        "title_en": "Review AI moderation suggestions in batches",
        "title_ru": "Проверяйте предложения ИИ по модерации сразу группой",
        "summary_en": (
            "Moderators can review or dismiss several AI suggestions together "
            "while keeping the final decision in human hands."
        ),
        "summary_ru": (
            "Модераторы могут проверить или отклонить сразу несколько предложений "
            "ИИ. Итоговое решение по-прежнему принимает человек."
        ),
        "action_label_en": "Read about AI moderation review",
        "action_label_ru": "Подробнее о проверке ИИ-модерации",
        "action_url": "/docs/ai/moderation-review",
    },
)


def upgrade() -> None:
    op.add_column(
        "product_release_notes",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_slug", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_title_en", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_title_ru", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_summary_en", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_summary_ru", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_action_label_en", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_action_label_ru", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_action_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "product_release_notes",
        sa.Column("public_image_url", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_product_release_notes_is_public",
        "product_release_notes",
        ["is_public"],
    )
    op.create_unique_constraint(
        "uq_product_release_notes_public_slug",
        "product_release_notes",
        ["public_slug"],
    )
    op.create_check_constraint(
        "ck_product_release_notes_public_copy",
        "product_release_notes",
        "NOT is_public OR ("
        "public_slug IS NOT NULL AND "
        "public_title_en IS NOT NULL AND public_title_ru IS NOT NULL AND "
        "public_summary_en IS NOT NULL AND public_summary_ru IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_product_release_notes_public_action",
        "product_release_notes",
        "(public_action_label_en IS NULL AND public_action_label_ru IS NULL AND "
        "public_action_url IS NULL) OR "
        "(public_action_label_en IS NOT NULL AND public_action_label_ru IS NOT NULL "
        "AND public_action_url IS NOT NULL)",
    )

    table = _release_notes_table()
    bind = op.get_bind()
    bind.execute(
        table.insert().values(
            id=NOTE_ID,
            published_at=datetime(2026, 8, 12, 8, 40, tzinfo=timezone.utc),
            title_en="Major Modral updates now have a public home",
            title_ru="У главных обновлений Modral появилась публичная страница",
            summary_en=(
                "The Modral website now highlights major features from the same "
                "release history used inside the product."
            ),
            summary_ru=(
                "На сайте Modral теперь собраны главные новые функции из той же "
                "истории обновлений, которую показывает панель."
            ),
            change_type="added",
            surface="both",
            feature_en="Product updates",
            feature_ru="Обновления продукта",
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=_json_literal(
                [
                    {
                        "en": (
                            "The homepage shows the latest major releases and links "
                            "to a complete public archive."
                        ),
                        "ru": (
                            "На главной странице показаны последние крупные обновления "
                            "и есть ссылка на полный публичный архив."
                        ),
                    },
                    {
                        "en": (
                            "Public updates stay concise, while the dashboard keeps "
                            "the detailed operational change history."
                        ),
                        "ru": (
                            "Публичные записи остаются краткими, а в панели сохраняется "
                            "подробная история изменений для работы команды."
                        ),
                    },
                    {
                        "en": "Updates can link directly to the relevant documentation.",
                        "ru": "Из обновления можно сразу перейти к нужному разделу документации.",
                    },
                ]
            ),
            is_published=True,
            is_public=True,
            public_slug="public-product-updates",
            public_title_en="See what we're building in Modral",
            public_title_ru="Следите за развитием Modral",
            public_summary_en=(
                "Major bot and dashboard releases now have a public archive, with "
                "short explanations and links to the features themselves."
            ),
            public_summary_ru=(
                "На публичной странице собраны главные обновления бота и панели: "
                "кратко, понятно и со ссылками на нужные функции."
            ),
            public_action_label_en=None,
            public_action_label_ru=None,
            public_action_url=None,
            public_image_url=None,
        )
    )

    for update in PUBLIC_UPDATES:
        bind.execute(
            table.update()
            .where(table.c.id == update["id"])
            .values(
                is_public=True,
                public_slug=update["slug"],
                public_title_en=update["title_en"],
                public_title_ru=update["title_ru"],
                public_summary_en=update["summary_en"],
                public_summary_ru=update["summary_ru"],
                public_action_label_en=update["action_label_en"],
                public_action_label_ru=update["action_label_ru"],
                public_action_url=update["action_url"],
            )
        )

    op.alter_column("product_release_notes", "is_public", server_default=None)


def downgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(table.delete().where(table.c.id == NOTE_ID))

    op.drop_constraint(
        "ck_product_release_notes_public_action",
        "product_release_notes",
        type_="check",
    )
    op.drop_constraint(
        "ck_product_release_notes_public_copy",
        "product_release_notes",
        type_="check",
    )
    op.drop_constraint(
        "uq_product_release_notes_public_slug",
        "product_release_notes",
        type_="unique",
    )
    op.drop_index(
        "ix_product_release_notes_is_public",
        table_name="product_release_notes",
    )
    op.drop_column("product_release_notes", "public_image_url")
    op.drop_column("product_release_notes", "public_action_url")
    op.drop_column("product_release_notes", "public_action_label_ru")
    op.drop_column("product_release_notes", "public_action_label_en")
    op.drop_column("product_release_notes", "public_summary_ru")
    op.drop_column("product_release_notes", "public_summary_en")
    op.drop_column("product_release_notes", "public_title_ru")
    op.drop_column("product_release_notes", "public_title_en")
    op.drop_column("product_release_notes", "public_slug")
    op.drop_column("product_release_notes", "is_public")
