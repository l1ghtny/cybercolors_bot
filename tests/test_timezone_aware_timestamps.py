import ast
from datetime import date, datetime, timezone
from pathlib import Path

import sqlalchemy as sa

from src.db.models import HistoricalUserActivityDaily, SQLModel, utcnow_utc_tz


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "d7e8f9a0b1c2_use_timezone_aware_timestamps.py"
)


def _migration_columns() -> dict[str, tuple[str, ...]]:
    module = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "INSTANT_COLUMNS"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("INSTANT_COLUMNS was not found in the timezone migration")


def _modeled_timestamp_columns() -> set[tuple[str, str]]:
    return {
        (table.name, column.name)
        for table in SQLModel.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, sa.DateTime)
    }


def test_all_modeled_timestamp_columns_are_timezone_aware():
    timestamp_columns = [
        column
        for table in SQLModel.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, sa.DateTime)
    ]

    assert timestamp_columns
    assert all(column.type.timezone is True for column in timestamp_columns)


def test_timezone_migration_covers_every_previously_naive_timestamp():
    migrated_columns = {
        (table_name, column_name)
        for table_name, column_names in _migration_columns().items()
        for column_name in column_names
    }
    created_timezone_aware = {
        ("global_users", "joined_discord"),
        ("member_notes", "created_at"),
        ("member_notes", "deleted_at"),
        ("product_release_notes", "created_at"),
        ("product_release_notes", "published_at"),
        ("users", "birthday_greeted_at"),
        ("users", "birthday_role_added_at"),
        ("server_gateway_installations", "joined_at"),
        ("server_gateway_installations", "left_at"),
        ("server_gateway_installations", "presence_updated_at"),
        ("scheduled_bot_post_attachments", "created_at"),
        ("scheduled_bot_post_runs", "created_at"),
        ("scheduled_bot_post_runs", "finished_at"),
        ("scheduled_bot_post_runs", "scheduled_for"),
        ("scheduled_bot_posts", "created_at"),
        ("scheduled_bot_posts", "last_run_at"),
        ("scheduled_bot_posts", "lease_until"),
        ("scheduled_bot_posts", "next_run_at"),
        ("scheduled_bot_posts", "updated_at"),
    }

    uncovered_columns = _modeled_timestamp_columns() - created_timezone_aware - migrated_columns

    assert not uncovered_columns


def test_calendar_dates_remain_date_only():
    column = HistoricalUserActivityDaily.__table__.c.activity_date

    assert isinstance(column.type, sa.Date)
    assert not isinstance(column.type, sa.DateTime)
    assert HistoricalUserActivityDaily(activity_date=date(2026, 7, 24)).activity_date == date(2026, 7, 24)


def test_utc_default_is_timezone_aware():
    value = utcnow_utc_tz()

    assert isinstance(value, datetime)
    assert value.tzinfo is timezone.utc
