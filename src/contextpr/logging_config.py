from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig

_RESERVED_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class KeyValueFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        parts = [
            f"time={self._quote(timestamp)}",
            f"level={self._quote(record.levelname)}",
            f"logger={self._quote(record.name)}",
            f"message={self._quote(record.getMessage())}",
        ]

        for key in sorted(self._extra_keys(record)):
            parts.append(f"{key}={self._quote(getattr(record, key))}")

        if record.exc_info:
            parts.append(f"exception={self._quote(self.formatException(record.exc_info))}")

        return " ".join(parts)

    @staticmethod
    def _extra_keys(record: logging.LogRecord) -> list[str]:
        return [
            key
            for key in record.__dict__
            if key not in _RESERVED_LOG_RECORD_FIELDS and not key.startswith("_")
        ]

    @staticmethod
    def _quote(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=True)


def configure_logging(level: str = "INFO") -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "contextpr": {
                    "()": "contextpr.logging_config.KeyValueFormatter",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "contextpr",
                    "level": level.upper(),
                }
            },
            "root": {
                "handlers": ["console"],
                "level": level.upper(),
            },
        }
    )
