import datetime
import logging
from logging.config import dictConfig


LOGGING_CONFIG = {
    "version": 1,
    "disabled_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
        },
        "standard": {
            "format": "%(levelname)-10s - %(asctime)s - %(name)-15s : %(message)s"
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "console2": {
            "level": "WARNING",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "file": {
            "level": "DEBUG",
            "formatter": "standard",
            "class": "modules.logs_setup.logger_settings.MyTimedRotatingFileHandler",
            "when": "h",
            "interval": 12,
            "filename": "./logs/main_log.log",
            "encoding": "utf-8"
        },
    },
    "loggers": {
        "bot": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False
        },
        "discord": {
            "handlers": ["console2", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
dictConfig(LOGGING_CONFIG)
