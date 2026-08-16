import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlmodel import select

from api.models.moderation_settings import ServerModerationSettingsUpdateModel
from api.routers.activity import (
    _build_activity_filters,
    _rank_leaderboard_rows,
    _resolve_effective_activity_excluded_channel_ids,
    _select_ranked_member,
    _sort_leaderboard_rows,
)
from src.db.models import MessageLog


def test_moderation_settings_update_normalizes_activity_excluded_channel_ids():
    body = ServerModerationSettingsUpdateModel(
        activity_excluded_channel_ids=["123", " 456 ", "123"],
    )

    assert body.activity_excluded_channel_ids == ["123", "456"]


def test_moderation_settings_update_allows_null_activity_excluded_channel_ids():
    body = ServerModerationSettingsUpdateModel(activity_excluded_channel_ids=None)

    assert body.activity_excluded_channel_ids is None


def test_moderation_settings_update_rejects_invalid_activity_excluded_channel_ids():
    with pytest.raises(ValidationError):
        ServerModerationSettingsUpdateModel(activity_excluded_channel_ids=["123", "not-a-channel"])


def test_leaderboard_server_excludes_merge_with_query_excludes_by_default():
    effective_excludes, applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids={111},
        server_excluded_channel_ids={222, 333},
        include_channel_ids=None,
        ignore_server_excludes=False,
    )

    assert effective_excludes == {111, 222, 333}
    assert applied is True


def test_leaderboard_include_channels_bypass_server_excludes():
    effective_excludes, applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids={111},
        server_excluded_channel_ids={222, 333},
        include_channel_ids={222},
        ignore_server_excludes=False,
    )

    assert effective_excludes == {111}
    assert applied is False


def test_leaderboard_ignore_server_excludes_bypasses_server_excludes():
    effective_excludes, applied = _resolve_effective_activity_excluded_channel_ids(
        query_excluded_channel_ids=None,
        server_excluded_channel_ids={222, 333},
        include_channel_ids=None,
        ignore_server_excludes=True,
    )

    assert effective_excludes is None
    assert applied is False


def test_leaderboard_can_order_least_active_before_applying_limit():
    rows = [
        (101, 900, None),
        (102, 12, None),
        (103, 45, None),
    ]

    ordered = _sort_leaderboard_rows(rows, "least_active")

    assert [row[0] for row in ordered[:2]] == [102, 103]
    assert rows[0][0] == 101


def test_leaderboard_assigns_competition_ranks_from_full_population():
    rows = [
        (101, 900, None),
        (102, 67, None),
        (103, 67, None),
        (104, 40, None),
    ]

    ranks = _rank_leaderboard_rows(rows, "most_active")

    assert ranks == {101: 1, 102: 2, 103: 2, 104: 4}


def test_leaderboard_assigns_least_active_ranks_from_full_population():
    rows = [
        (101, 1, None),
        (102, 1, None),
        (103, 4, None),
    ]

    ranks = _rank_leaderboard_rows(rows, "least_active")

    assert ranks == {101: 1, 102: 1, 103: 3}


def test_ranked_member_is_selected_only_after_ranking_full_population():
    rows = [
        (101, 900, None),
        (102, 68, None),
        (103, 67, None),
        (104, 40, None),
    ]

    selected, ranks, population = _select_ranked_member(rows, "most_active", 103)

    assert selected == [(103, 67, None)]
    assert ranks[103] == 3
    assert population == 4


def test_live_activity_filters_out_buckets_already_covered_by_historical_import():
    conditions = _build_activity_filters(server_id=123)
    compiled = str(
        select(MessageLog.user_id)
        .where(*conditions)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "NOT (EXISTS" in compiled
    assert "FROM historical_user_activity_daily" in compiled
    assert "historical_user_activity_daily.server_id = message_log.server_id" in compiled
    assert "historical_user_activity_daily.user_id = message_log.user_id" in compiled
    assert "historical_user_activity_daily.channel_id = message_log.channel_id" in compiled
    assert "historical_user_activity_daily.activity_date = CAST(timezone('UTC', message_log.created_at) AS DATE)" in compiled
