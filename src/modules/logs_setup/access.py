from __future__ import annotations

import logging


class HealthCheckAccessFilter(logging.Filter):
    """Hide successful health probes from Uvicorn's access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True

        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True

        path = str(args[2]).partition("?")[0]
        status_code = args[4]
        return (
            path != "/healthz"
            or not isinstance(status_code, int)
            or status_code >= 400
        )


def configure_api_access_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, HealthCheckAccessFilter) for item in access_logger.filters):
        access_logger.addFilter(HealthCheckAccessFilter())
