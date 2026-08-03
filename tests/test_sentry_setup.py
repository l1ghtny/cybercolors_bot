from __future__ import annotations

import sentry_sdk

from src.modules.observability.sentry import (
    BIRTHDAY_MONITOR_SLUG,
    birthday_hourly_monitor,
    configure_sentry,
)


def test_configure_sentry_is_disabled_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    called = False

    def fake_init(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(sentry_sdk, "init", fake_init)

    assert configure_sentry("api") is False
    assert called is False


def test_configure_sentry_uses_private_low_noise_defaults(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.2")
    captured = {}
    tags = {}

    def fake_init(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    monkeypatch.setattr(sentry_sdk, "set_tag", tags.__setitem__)

    assert configure_sentry("discord-bot") is True
    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["enable_logs"] is False
    assert tags == {"service": "discord-bot"}
    assert captured["traces_sampler"](
        {"transaction_context": {"name": "GET /healthz"}}
    ) == 0.0
    assert captured["traces_sampler"](
        {"transaction_context": {"name": "GET /servers"}}
    ) == 0.2

    event = {
        "request": {
            "headers": {
                "Authorization": "secret",
                "Content-Type": "application/json",
                "Cookie": "session=secret",
            },
            "cookies": {"session": "secret"},
            "data": {"message": "private"},
        },
        "user": {
            "id": "123",
            "email": "private@example.invalid",
            "username": "private",
            "ip_address": "127.0.0.1",
        },
    }
    scrubbed = captured["before_send"](event, {})
    assert scrubbed["request"] == {"headers": {"Content-Type": "application/json"}}
    assert scrubbed["user"] == {"id": "123"}


def test_birthday_monitor_uses_hourly_utc_schedule(monkeypatch):
    captured = {}
    marker = object()

    def fake_monitor(*, monitor_slug, monitor_config):
        captured["slug"] = monitor_slug
        captured["config"] = monitor_config
        return marker

    monkeypatch.setattr(sentry_sdk, "monitor", fake_monitor)

    assert birthday_hourly_monitor() is marker
    assert captured["slug"] == BIRTHDAY_MONITOR_SLUG
    assert captured["config"]["schedule"] == {
        "type": "crontab",
        "value": "0 * * * *",
    }
    assert captured["config"]["timezone"] == "UTC"
