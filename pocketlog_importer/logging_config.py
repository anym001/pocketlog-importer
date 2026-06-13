"""Central logging setup, mirroring PocketLog's conventions.

Single ``pocketlog_importer`` logger namespace with its own stderr handler (visible
in ``docker logs``) and an optional rotating ``LOG_FILE``. The uniform format
and second-precision datefmt match PocketLog so logs read consistently across
both containers.

ENV:
  LOG_LEVEL          default INFO
  LOG_FORMAT         "text" (default) or "json" (one JSON object per line)
  LOG_FILE           optional path to an additional rotating file handler
  LOG_FILE_MAX_BYTES default 1 MiB
  LOG_FILE_BACKUPS   default 5
"""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "pocketlog_importer"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


class JsonFormatter(logging.Formatter):
    """Render each record as one JSON object per line.

    Carries the same fields as the text format (``time``, ``level``,
    ``logger``, ``message``) so both formats convey identical information; an
    ``exc_info`` field is added only when an exception is being logged. The
    timestamp uses :data:`DATEFMT`, so a line's time reads the same in either
    format. ``json.dumps`` escapes embedded newlines, so JSON output needs no
    separate log-forging guard. Selected via ``LOG_FORMAT=json``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, DATEFMT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_formatter() -> logging.Formatter:
    """Pick the formatter from ``LOG_FORMAT`` (text default, json optional)."""
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        return JsonFormatter()
    return logging.Formatter(LOG_FORMAT, datefmt=DATEFMT)


def configure_logging() -> logging.Logger:
    """Configure and return the package logger. Idempotent."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:  # already configured (e.g. re-entry in tests)
        return logger

    formatter = _build_formatter()

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    log_file = os.getenv("LOG_FILE")
    if log_file:
        # An unwritable log file must never take the container down: warn and
        # keep running on stderr only.
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=int(os.getenv("LOG_FILE_MAX_BYTES", str(1024 * 1024))),
                backupCount=int(os.getenv("LOG_FILE_BACKUPS", "5")),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Could not open LOG_FILE %s: %s", log_file, exc)

    return logger


def safe(value: object, *, max_len: int = 256) -> str:
    """Sanitise an externally-controlled string for plain-text logging.

    Strips CR/LF (and other control chars) so a crafted filename or an API
    error value echoed back from bank-CSV content can't forge extra log
    lines, and truncates to bound length. Mirrors PocketLog's logging hardening.
    """
    s = "" if value is None else str(value)
    s = "".join(" " if (c == "\n" or c == "\r" or ord(c) < 32) else c for c in s)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def get_logger(suffix: str | None = None) -> logging.Logger:
    """Return a child logger under the package namespace."""
    name = LOGGER_NAME if not suffix else f"{LOGGER_NAME}.{suffix}"
    return logging.getLogger(name)
