import re
from dataclasses import dataclass

from discord import app_commands


MAX_ACTION_DURATION_MINUTES = 43_200
DURATION_UNIT_MINUTES = {
    "minutes": 1,
    "hours": 60,
    "days": 1_440,
    "weeks": 10_080,
    "months": 43_200,
}
COMPACT_DURATION_UNITS = {
    "m": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
    "w": "weeks",
    "week": "weeks",
    "weeks": "weeks",
    "mo": "months",
    "month": "months",
    "months": "months",
}
DURATION_PRESET_MINUTES = {
    "10m": 10,
    "30m": 30,
    "1h": 60,
    "6h": 360,
    "12h": 720,
    "1d": 1_440,
    "3d": 4_320,
    "1w": 10_080,
    "2w": 20_160,
    "30d": 43_200,
}
DURATION_PRESET_LABELS = {
    "10m": "10 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "6h": "6 hours",
    "12h": "12 hours",
    "1d": "1 day",
    "3d": "3 days",
    "1w": "1 week",
    "2w": "2 weeks",
    "30d": "30 days",
}
DEFAULT_DURATION_VALUE = "default"
PERMANENT_DURATION_VALUE = "permanent"


@dataclass(frozen=True)
class DurationSelection:
    minutes: int | None
    label: str
    is_permanent: bool = False


def duration_unit_choices() -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name="minutes", value="minutes"),
        app_commands.Choice(name="hours", value="hours"),
        app_commands.Choice(name="days", value="days"),
        app_commands.Choice(name="weeks", value="weeks"),
        app_commands.Choice(name="months", value="months"),
    ]


def action_duration_choices(*, include_default: bool = False, include_permanent: bool = False) -> list[app_commands.Choice[str]]:
    choices: list[app_commands.Choice[str]] = []
    if include_default:
        choices.append(app_commands.Choice(name="server default", value=DEFAULT_DURATION_VALUE))
    if include_permanent:
        choices.append(app_commands.Choice(name="permanent", value=PERMANENT_DURATION_VALUE))
    choices.extend(
        app_commands.Choice(name=label, value=value)
        for value, label in DURATION_PRESET_LABELS.items()
    )
    return choices


def format_duration_minutes(minutes: int) -> str:
    for unit_name, unit_minutes in (("month", 43_200), ("week", 10_080), ("day", 1_440), ("hour", 60)):
        if minutes >= unit_minutes and minutes % unit_minutes == 0:
            amount = minutes // unit_minutes
            suffix = "" if amount == 1 else "s"
            return f"{amount} {unit_name}{suffix}"
    suffix = "" if minutes == 1 else "s"
    return f"{minutes} minute{suffix}"


def parse_duration_text(value: str, *, max_minutes: int = MAX_ACTION_DURATION_MINUTES) -> DurationSelection:
    normalized = value.strip().lower()
    preset_minutes = DURATION_PRESET_MINUTES.get(normalized)
    if preset_minutes is not None:
        if preset_minutes > max_minutes:
            raise ValueError(f"Duration exceeds the server maximum of {format_duration_minutes(max_minutes)}.")
        return DurationSelection(minutes=preset_minutes, label=DURATION_PRESET_LABELS[normalized])

    match = re.fullmatch(r"(\d+)\s*([a-z]+)", normalized)
    if match is None:
        raise ValueError("Use a duration like 30m, 2h, 3d, or 1w.")

    amount = int(match.group(1))
    unit = COMPACT_DURATION_UNITS.get(match.group(2))
    if amount <= 0 or unit is None:
        raise ValueError("Use a duration like 30m, 2h, 3d, or 1w.")

    minutes = amount * DURATION_UNIT_MINUTES[unit]
    if minutes > max_minutes:
        raise ValueError(f"Duration exceeds the server maximum of {format_duration_minutes(max_minutes)}.")
    return DurationSelection(minutes=minutes, label=format_duration_minutes(minutes))


def resolve_duration_selection(
    *,
    preset: app_commands.Choice[str] | str | None,
    custom_value: int | None,
    custom_unit: app_commands.Choice[str] | str | None,
    default_minutes: int | None,
    max_minutes: int = MAX_ACTION_DURATION_MINUTES,
    allow_default: bool = False,
    allow_permanent: bool = False,
) -> DurationSelection:
    preset_value = preset.value if hasattr(preset, "value") else preset
    unit_value = custom_unit.value if hasattr(custom_unit, "value") else custom_unit

    if custom_value is None and unit_value is not None:
        raise ValueError("Set duration_value when using duration_unit.")

    if custom_value is not None:
        unit = unit_value or "minutes"
        if unit not in DURATION_UNIT_MINUTES:
            raise ValueError("Invalid duration unit.")
        minutes = custom_value * DURATION_UNIT_MINUTES[unit]
        if minutes > max_minutes:
            raise ValueError(f"Duration exceeds the server maximum of {format_duration_minutes(max_minutes)}.")
        return DurationSelection(minutes=minutes, label=format_duration_minutes(minutes))

    if preset_value == PERMANENT_DURATION_VALUE:
        if not allow_permanent:
            raise ValueError("Permanent duration is not available for this action.")
        return DurationSelection(minutes=None, label="permanent", is_permanent=True)

    if preset_value == DEFAULT_DURATION_VALUE:
        if not allow_default or default_minutes is None:
            raise ValueError("Server default duration is not available for this action.")
        if default_minutes > max_minutes:
            raise ValueError(f"Server default exceeds the maximum of {format_duration_minutes(max_minutes)}.")
        return DurationSelection(minutes=default_minutes, label=format_duration_minutes(default_minutes))

    if preset_value:
        if preset_value not in DURATION_PRESET_MINUTES:
            raise ValueError("Invalid duration preset.")
        minutes = DURATION_PRESET_MINUTES[preset_value]
        if minutes > max_minutes:
            raise ValueError(f"Duration exceeds the server maximum of {format_duration_minutes(max_minutes)}.")
        return DurationSelection(minutes=minutes, label=DURATION_PRESET_LABELS[preset_value])

    if allow_default and default_minutes is not None:
        if default_minutes > max_minutes:
            raise ValueError(f"Server default exceeds the maximum of {format_duration_minutes(max_minutes)}.")
        return DurationSelection(minutes=default_minutes, label=format_duration_minutes(default_minutes))

    if allow_permanent:
        return DurationSelection(minutes=None, label="permanent", is_permanent=True)

    raise ValueError("Duration is required.")
