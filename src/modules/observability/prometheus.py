from __future__ import annotations

from time import perf_counter

from fastapi import FastAPI, Request
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app, start_http_server
from starlette.middleware.base import BaseHTTPMiddleware


HTTP_REQUESTS = Counter(
    "cybercolors_http_requests_total",
    "Completed HTTP requests handled by CyberColors services.",
    ("service", "method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "cybercolors_http_request_duration_seconds",
    "HTTP request duration handled by CyberColors services.",
    ("service", "method", "route", "status"),
)
DISCORD_GATEWAY_CONNECTED = Gauge(
    "cybercolors_discord_gateway_connected",
    "Whether the CyberColors Discord gateway is ready (1) or disconnected (0).",
)
MESSAGE_INGESTION_QUEUE_DEPTH = Gauge(
    "cybercolors_message_ingestion_queue_depth",
    "Current number of messages waiting for archival processing.",
)
MESSAGE_INGESTION_MESSAGES = Counter(
    "cybercolors_message_ingestion_messages_total",
    "Messages handled by the archival ingestion pipeline.",
    ("outcome",),
)
AI_MODERATION_DECISIONS = Counter(
    "cybercolors_ai_moderation_decisions_total",
    "Completed AI moderation checks by outcome.",
    ("outcome",),
)
AI_MODERATION_DURATION = Histogram(
    "cybercolors_ai_moderation_duration_seconds",
    "Duration of AI moderation provider checks.",
)

_EXCLUDED_PATHS = {"/healthz", "/metrics"}


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "unmatched"


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, service_name: str) -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            labels = {
                "service": self.service_name,
                "method": request.method,
                "route": _route_label(request),
                "status": str(status_code),
            }
            elapsed = perf_counter() - started_at
            HTTP_REQUESTS.labels(**labels).inc()
            HTTP_REQUEST_DURATION.labels(**labels).observe(elapsed)


def instrument_fastapi_app(app: FastAPI, *, service_name: str) -> None:
    """Expose standard Prometheus metrics without high-cardinality URL labels."""
    app.add_middleware(PrometheusMetricsMiddleware, service_name=service_name)
    app.mount("/metrics", make_asgi_app())


def start_bot_metrics_server(port: int = 9100) -> None:
    """Expose bot-process metrics on an internal Kubernetes port."""
    start_http_server(port)
