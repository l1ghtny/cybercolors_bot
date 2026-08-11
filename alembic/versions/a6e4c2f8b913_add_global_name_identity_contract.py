"""Persist Discord global names and clarify member identity rendering.

Revision ID: a6e4c2f8b913
Revises: f2b8d4e6a913
Create Date: 2026-08-12 01:20:00.000000
"""

from datetime import datetime, timezone
import json

from alembic import op
import sqlalchemy as sa


revision = "a6e4c2f8b913"
down_revision = "f2b8d4e6a913"
branch_labels = None
depends_on = None


NOTE_ID = "2026-08-11-member-name-preference-v2"


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
    )


def _json_literal(value: list[dict[str, str]]) -> sa.ColumnElement:
    """Render JSON safely in both online and Alembic ``--sql`` migrations."""
    return sa.cast(
        op.inline_literal(
            json.dumps(value, ensure_ascii=False),
            type_=sa.Text(),
        ),
        sa.JSON(),
    )


def upgrade() -> None:
    op.add_column(
        "global_users",
        sa.Column("global_name", sa.String(length=100), nullable=True),
    )

    table = _release_notes_table()
    op.get_bind().execute(
        table.update()
        .where(table.c.id == NOTE_ID)
        .values(
            published_at=datetime(2026, 8, 12, 1, 20, tzinfo=timezone.utc),
            title_en="Member names now follow Discord consistently",
            title_ru="Имена участников теперь везде отображаются одинаково",
            summary_en=(
                "The dashboard shows the server nickname first, then the global "
                "Discord name, while keeping @username as supporting context."
            ),
            summary_ru=(
                "Панель сначала показывает никнейм на сервере, затем глобальное "
                "имя в Discord, а @имя пользователя оставляет рядом для уточнения."
            ),
            change_type="improved",
            surface="both",
            feature_en="Members · Discord identity",
            feature_ru="Участники · Имена в Discord",
            action_label_en="Open members",
            action_label_ru="Открыть участников",
            action_path="/dashboard/{server_id}/users",
            changes=_json_literal([
                {
                    "en": (
                        "Member names no longer depend on a browser setting: the "
                        "server nickname is used whenever it exists."
                    ),
                    "ru": (
                        "Отображение имён больше не зависит от настройки браузера: "
                        "если у участника есть никнейм на сервере, панель показывает его."
                    ),
                },
                {
                    "en": (
                        "Without a server nickname, the global Discord name is used; "
                        "@username remains visible and is never duplicated."
                    ),
                    "ru": (
                        "Если никнейма на сервере нет, используется глобальное имя в "
                        "Discord; @имя пользователя остаётся рядом и не дублируется."
                    ),
                },
                {
                    "en": (
                        "The full member profile labels the server nickname, global "
                        "name, username, and Discord ID separately."
                    ),
                    "ru": (
                        "В полном профиле отдельно указаны никнейм на сервере, "
                        "глобальное имя, имя пользователя и ID Discord."
                    ),
                },
            ]),
        )
    )


def downgrade() -> None:
    table = _release_notes_table()
    op.get_bind().execute(
        table.update()
        .where(table.c.id == NOTE_ID)
        .values(
            published_at=datetime(2026, 8, 11, 20, tzinfo=timezone.utc),
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
            change_type="improved",
            surface="dashboard",
            feature_en="Personal settings · Member names",
            feature_ru="Личные настройки · Имена участников",
            action_label_en=None,
            action_label_ru=None,
            action_path=None,
            changes=_json_literal([
                {
                    "en": (
                        "Open Personal settings and choose Server name first or "
                        "Username first."
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
                        "Выбор сохраняется в этом браузере и действует во всей панели."
                    ),
                },
            ]),
        )
    )
    op.drop_column("global_users", "global_name")
