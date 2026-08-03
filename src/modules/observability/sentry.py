from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration


DEFAULT_TRACES_SAMPLE_RATE = 0.05
BIRTHDAY_MONITOR_SLUG = "cybercolors-birthday-hourly"

_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
}


def _env_sample_rate(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return max(0.0, min(1.0, value))


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        request.pop("data", None)
        headers = request.get("headers")
        if isinstance(headers, Mapping):
            request["headers"] = {
                key: value
                for key, value in headers.items()
                if str(key).lower() not in _SENSITIVE_HEADERS
            }

    user = event.get("user")
    if isinstance(user, dict):
        for key in ("email", "ip_address", "name", "username"):
            user.pop(key, None)

    return event


def configure_sentry(service_name: str) -> bool:
    """Initialize Sentry when a DSN is configured for this process."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    traces_sample_rate = _env_sample_rate(
        "SENTRY_TRACES_SAMPLE_RATE", DEFAULT_TRACES_SAMPLE_RATE
    )

    def traces_sampler(sampling_context: dict[str, Any]) -> float:
        transaction_context = sampling_context.get("transaction_context") or {}
        transaction_name = str(transaction_context.get("name", ""))
        if transaction_name.endswith("/healthz"):
            return 0.0
        return traces_sample_rate

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE") or None,
        integrations=[
            AsyncioIntegration(),
            LoggingIntegration(
                level=logging.WARNING,
                event_level=logging.ERROR,
                sentry_logs_level=None,
            ),
        ],
        traces_sampler=traces_sampler,
        sample_rate=1.0,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        enable_logs=False,
        before_send=_before_send,
    )
    sentry_sdk.set_tag("service", service_name)
    return True


def birthday_hourly_monitor():
    """Create a check-in context for the hourly birthday and role cleanup task."""
    return sentry_sdk.monitor(
        monitor_slug=BIRTHDAY_MONITOR_SLUG,
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 * * * *"},
            "checkin_margin": 10,
            "max_runtime": 30,
            "timezone": "UTC",
        },
    )
