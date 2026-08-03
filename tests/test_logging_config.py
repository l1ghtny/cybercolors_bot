import logging

from src.modules.logs_setup import logger as logs_setup
from src.modules.logs_setup.access import (
    HealthCheckAccessFilter,
    configure_api_access_logging,
)


def test_http_client_info_logs_are_suppressed():
    for logger_name in ("httpx", "httpcore"):
        logger_config = logs_setup.LOGGING_CONFIG["loggers"][logger_name]

        assert logger_config["level"] == "WARNING"
        assert logger_config["propagate"] is False
        assert logging.getLogger(logger_name).getEffectiveLevel() == logging.WARNING


def _access_record(path: str, status_code: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", path, "1.1", status_code),
        None,
    )


def test_healthcheck_access_filter_hides_only_successful_probes():
    access_filter = HealthCheckAccessFilter()

    assert access_filter.filter(_access_record("/healthz", 200)) is False
    assert access_filter.filter(_access_record("/healthz?full=1", 204)) is False
    assert access_filter.filter(_access_record("/healthz", 503)) is True
    assert access_filter.filter(_access_record("/servers", 200)) is True


def test_api_access_filter_is_installed_once():
    access_logger = logging.getLogger("uvicorn.access")
    existing = list(access_logger.filters)
    access_logger.filters.clear()
    try:
        configure_api_access_logging()
        configure_api_access_logging()
        assert sum(
            isinstance(item, HealthCheckAccessFilter)
            for item in access_logger.filters
        ) == 1
    finally:
        access_logger.filters[:] = existing
