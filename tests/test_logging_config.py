import logging

from src.modules.logs_setup import logger as logs_setup


def test_http_client_info_logs_are_suppressed():
    for logger_name in ("httpx", "httpcore"):
        logger_config = logs_setup.LOGGING_CONFIG["loggers"][logger_name]

        assert logger_config["level"] == "WARNING"
        assert logger_config["propagate"] is False
        assert logging.getLogger(logger_name).getEffectiveLevel() == logging.WARNING
