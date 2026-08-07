import asyncio
import json
from pathlib import Path

from src.modules.birthdays_module.hourly_check import check_roles
from src.modules.observability.bot_metrics import (
    BIRTHDAY_ROLE_CLEANUP_PENDING,
    BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS,
    BIRTHDAY_ROLE_REMOVALS,
)


def test_birthday_role_metrics_use_only_bounded_outcome_labels():
    assert BIRTHDAY_ROLE_REMOVALS._name == "cybercolors_birthday_role_removals"
    assert BIRTHDAY_ROLE_REMOVALS._labelnames == ("outcome",)
    assert (
        BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS._name
        == "cybercolors_birthday_role_cleanup_memberships"
    )
    assert BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS._labelnames == ("outcome",)
    assert BIRTHDAY_ROLE_CLEANUP_PENDING._name == "cybercolors_birthday_role_cleanup_pending"
    assert BIRTHDAY_ROLE_CLEANUP_PENDING._labelnames == ()


def test_manual_birthday_check_does_not_overwrite_scheduled_pending_gauge():
    previous_value = BIRTHDAY_ROLE_CLEANUP_PENDING._value.get()
    BIRTHDAY_ROLE_CLEANUP_PENDING.set(7)
    try:
        asyncio.run(
            check_roles.check_roles(
                object(),
                guild_ids=set(),
                update_pending_metric=False,
            )
        )
        assert BIRTHDAY_ROLE_CLEANUP_PENDING._value.get() == 7
    finally:
        BIRTHDAY_ROLE_CLEANUP_PENDING.set(previous_value)


def test_runtime_dashboard_exposes_birthday_role_cleanup_metrics():
    dashboard_path = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "k8s"
        / "observability"
        / "dashboards"
        / "cybercolors-runtime.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    outcomes_query = panels["Birthday role removal outcomes (24h)"]["targets"][0]["expr"]
    pending_query = panels["Birthday role cleanups pending"]["targets"][0]["expr"]
    retries_query = panels["Birthday role cleanup retries (24h)"]["targets"][0]["expr"]

    assert "cybercolors_birthday_role_removals_total" in outcomes_query
    assert "cybercolors_birthday_role_cleanup_pending" in pending_query
    assert "cybercolors_birthday_role_cleanup_memberships_total" in retries_query
    assert 'outcome=~"retry_pending|invalid_timestamp|database_error"' in retries_query
