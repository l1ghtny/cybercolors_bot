import pytest
from discord import app_commands

from src.modules.moderation.durations import (
    action_duration_choices,
    duration_unit_choices,
    parse_duration_text,
    resolve_duration_selection,
)


def test_duration_preset_resolves_to_minutes_and_label():
    selected = resolve_duration_selection(
        preset=app_commands.Choice(name="1 hour", value="1h"),
        custom_value=None,
        custom_unit=None,
        default_minutes=None,
    )

    assert selected.minutes == 60
    assert selected.label == "1 hour"
    assert selected.is_permanent is False


def test_custom_duration_value_and_unit_wins_over_preset():
    selected = resolve_duration_selection(
        preset=app_commands.Choice(name="10 minutes", value="10m"),
        custom_value=2,
        custom_unit=app_commands.Choice(name="days", value="days"),
        default_minutes=None,
    )

    assert selected.minutes == 2880
    assert selected.label == "2 days"


def test_default_and_permanent_duration_modes():
    muted = resolve_duration_selection(
        preset=None,
        custom_value=None,
        custom_unit=None,
        default_minutes=45,
        allow_default=True,
        allow_permanent=False,
    )
    banned = resolve_duration_selection(
        preset=None,
        custom_value=None,
        custom_unit=None,
        default_minutes=None,
        allow_default=False,
        allow_permanent=True,
    )

    assert muted.minutes == 45
    assert muted.label == "45 minutes"
    assert banned.minutes is None
    assert banned.label == "permanent"
    assert banned.is_permanent is True


def test_custom_duration_cannot_exceed_maximum():
    with pytest.raises(ValueError, match="maximum"):
        resolve_duration_selection(
            preset=None,
            custom_value=6,
            custom_unit="weeks",
            default_minutes=None,
            max_minutes=30_240,
        )


def test_parse_duration_text_accepts_compact_and_natural_units():
    assert parse_duration_text("30m").minutes == 30
    assert parse_duration_text("2 hours").minutes == 120
    assert parse_duration_text("3d").label == "3 days"
    assert parse_duration_text("1w").label == "1 week"
    assert parse_duration_text("1 month").minutes == 43200


def test_duration_choices_fit_discord_choice_limit():
    assert len(action_duration_choices(include_default=True)) <= 25
    assert len(action_duration_choices(include_permanent=True)) <= 25
    assert [choice.value for choice in duration_unit_choices()] == ["minutes", "hours", "days", "weeks", "months"]


def test_duration_unit_requires_custom_value():
    with pytest.raises(ValueError, match="duration_value"):
        resolve_duration_selection(
            preset="1h",
            custom_value=None,
            custom_unit="hours",
            default_minutes=None,
        )
