"""Configure a JSON-line logger writing to stdout."""

import logging
import sys

import orjson


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record to stdout."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload).decode()


def configure_logging(level: int = logging.INFO) -> None:
    """Set up root logger with JSON-line output to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
