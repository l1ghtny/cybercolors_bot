from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from api.api_main import app
from api.models.scheduled_posts import ScheduledPostWriteModel
from api.services.scheduled_posts import _next_occurrence
from src.db.models import ScheduledBotPost


def test_scheduled_post_payload_requires_timezone_aware_time_and_interval() -> None:
    with pytest.raises(ValidationError):
        ScheduledPostWriteModel(
            channel_id="123",
            content="Announcement",
            schedule_type="once",
            next_run_at=datetime(2026, 8, 1, 12, 0),
        )

    with pytest.raises(ValidationError):
        ScheduledPostWriteModel(
            channel_id="123",
            content="Announcement",
            schedule_type="interval",
            next_run_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )

    payload = ScheduledPostWriteModel(
        channel_id="123",
        content="Announcement",
        schedule_type="interval",
        timezone="Europe/Bratislava",
        next_run_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        interval_seconds=3600,
    )
    assert payload.interval_seconds == 3600


def test_next_occurrence_skips_missed_intervals_without_bursting() -> None:
    start = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    post = ScheduledBotPost(
        server_id=1,
        channel_id=2,
        created_by_user_id=3,
        updated_by_user_id=3,
        content="Announcement",
        schedule_type="interval",
        timezone="UTC",
        interval_seconds=3600,
        next_run_at=start,
    )
    assert _next_occurrence(post, now=start + timedelta(hours=3, minutes=20)) == start + timedelta(hours=4)


def test_scheduled_post_routes_require_manage_permission() -> None:
    expected = {
        ("GET", "/servers/{server_id}/scheduled-posts"),
        ("GET", "/servers/{server_id}/scheduled-posts/runs"),
        ("POST", "/servers/{server_id}/scheduled-posts"),
        ("POST", "/servers/{server_id}/scheduled-posts/media"),
        ("PUT", "/servers/{server_id}/scheduled-posts/{post_id}"),
        ("PUT", "/servers/{server_id}/scheduled-posts/{post_id}/media"),
        ("PATCH", "/servers/{server_id}/scheduled-posts/{post_id}/status"),
        ("POST", "/servers/{server_id}/scheduled-posts/{post_id}/send-now"),
        ("DELETE", "/servers/{server_id}/scheduled-posts/{post_id}"),
    }
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            key = (method, route.path)
            if key not in expected:
                continue
            permissions = {
                dependency.call.permission_key
                for dependency in route.dependant.dependencies
                if hasattr(dependency.call, "permission_key")
            }
            assert permissions == {"communications.scheduled_posts.manage"}
            found.add(key)
    assert found == expected
