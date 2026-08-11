"""Clarify what the member-name preference changes.

Revision ID: f2b8d4e6a913
Revises: e4a1c7d9b205
Create Date: 2026-08-12 00:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f2b8d4e6a913"
down_revision = "e4a1c7d9b205"
branch_labels = None
depends_on = None


NOTE_ID = "2026-08-11-member-name-preference-v2"


def _release_notes_table() -> sa.TableClause:
    return sa.table(
        "product_release_notes",
        sa.column("id", sa.String),
        sa.column("title_en", sa.String),
        sa.column("title_ru", sa.String),
        sa.column("summary_en", sa.Text),
        sa.column("summary_ru", sa.Text),
        sa.column("changes", sa.JSON),
    )


def upgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(
        table.update()
        .where(table.c.id == NOTE_ID)
        .values(
            title_en="Choose which member name appears first",
            title_ru="Выберите, какое имя участника показывать первым",
            summary_en=(
                "The preference changes the primary member name; it does not "
                "hide the Discord @username shown as supporting context."
            ),
            summary_ru=(
                "Настройка меняет основное имя участника, но не скрывает его "
                "@имя пользователя Discord."
            ),
            changes=[
                {
                    "en": (
                        "Open Personal settings and choose Server name first "
                        "or Username first."
                    ),
                    "ru": (
                        "Откройте личные настройки и выберите «Имя на сервере "
                        "первым» или «Имя пользователя первым»."
                    ),
                },
                {
                    "en": (
                        "Member lists and profiles continue to show @username "
                        "alongside the primary name."
                    ),
                    "ru": (
                        "В списках и профилях @имя пользователя по-прежнему "
                        "показывается рядом с основным именем."
                    ),
                },
                {
                    "en": (
                        "The preference is stored in this browser and applies "
                        "throughout the dashboard."
                    ),
                    "ru": (
                        "Выбор сохраняется в этом браузере и действует во всей "
                        "панели."
                    ),
                },
            ],
        )
    )


def downgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(
        table.update()
        .where(table.c.id == NOTE_ID)
        .values(
            title_en="Choose which member name the dashboard shows",
            title_ru="Выберите, какое имя участника показывать",
            summary_en=(
                "The old name switcher has been replaced with one clear "
                "personal preference."
            ),
            summary_ru=(
                "Вместо непонятного переключателя теперь есть одна настройка "
                "отображения имён."
            ),
            changes=[
                {
                    "en": (
                        "Open the person icon in the top-right corner and choose "
                        "Server name or Discord @username."
                    ),
                    "ru": (
                        "Нажмите на значок человека в правом верхнем углу и "
                        "выберите имя на сервере или @имя пользователя Discord."
                    ),
                },
                {
                    "en": (
                        "The choice is stored in this browser and applies "
                        "throughout the dashboard."
                    ),
                    "ru": (
                        "Выбор сохраняется в этом браузере и действует во всей "
                        "панели."
                    ),
                },
            ],
        )
    )
