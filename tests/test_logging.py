import json
import logging
import sys

from pocketlog_importer.logging_config import (
    LOGGER_NAME,
    JsonFormatter,
    configure_logging,
    safe,
)


def _reset():
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)


def test_configure_is_idempotent(monkeypatch):
    monkeypatch.delenv("LOG_FILE", raising=False)
    _reset()
    logger = configure_logging()
    count = len(logger.handlers)
    configure_logging()
    assert len(logger.handlers) == count  # no duplicate handlers
    assert logger.propagate is False


def test_log_file_handler(tmp_path, monkeypatch):
    _reset()
    log_path = tmp_path / "logs" / "importer.log"
    monkeypatch.setenv("LOG_FILE", str(log_path))
    logger = configure_logging()
    logger.info("hello")
    assert log_path.exists()
    assert "hello" in log_path.read_text(encoding="utf-8")


def test_unwritable_log_file_does_not_crash(monkeypatch):
    _reset()
    # A path under an existing file can't be created as a directory.
    monkeypatch.setenv("LOG_FILE", "/dev/null/nope/importer.log")
    logger = configure_logging()  # must not raise
    assert logger is not None


def test_safe_strips_control_chars_and_truncates():
    assert safe("a\r\nb") == "a  b"
    assert safe("tab\tend") == "tab end"
    assert safe(None) == ""
    long = "x" * 500
    assert safe(long, max_len=10) == "x" * 10 + "…"


def test_safe_prevents_log_line_forging():
    # A crafted filename / API error value with CRLF must collapse to a single
    # line so it cannot inject a forged log record.
    forged = "real.csv\n2099-01-01 00:00:00 ERROR pocketlog_importer forged event"
    out = safe(forged)
    assert "\n" not in out and "\r" not in out


def _record(
    msg, args=(), *, name="pocketlog_importer.notify", level=logging.INFO, exc=None
):
    return logging.LogRecord(name, level, "f.py", 1, msg, args, exc)


def test_json_formatter_fields_mirror_text():
    out = JsonFormatter().format(_record("Notification sent: %s", ("OK",)))
    data = json.loads(out)
    assert data["level"] == "INFO"
    assert data["logger"] == "pocketlog_importer.notify"
    assert data["message"] == "Notification sent: OK"  # %-args applied
    assert "time" in data
    assert "exc_info" not in data  # only present when logging an exception


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        rec = _record(
            "crash", name="pocketlog_importer", level=logging.ERROR, exc=sys.exc_info()
        )
    data = json.loads(JsonFormatter().format(rec))
    assert "ValueError: boom" in data["exc_info"]


def test_json_formatter_escapes_newlines():
    # An embedded newline must stay inside the JSON string (one line out),
    # so JSON output cannot be used to forge a second log record.
    out = JsonFormatter().format(_record("line1\nline2"))
    assert "\n" not in out
    assert json.loads(out)["message"] == "line1\nline2"


def test_configure_logging_selects_json(monkeypatch):
    monkeypatch.delenv("LOG_FILE", raising=False)
    monkeypatch.setenv("LOG_FORMAT", "json")
    _reset()
    logger = configure_logging()
    assert all(isinstance(h.formatter, JsonFormatter) for h in logger.handlers)
    _reset()


def test_configure_logging_defaults_to_text(monkeypatch):
    monkeypatch.delenv("LOG_FILE", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    _reset()
    logger = configure_logging()
    assert all(not isinstance(h.formatter, JsonFormatter) for h in logger.handlers)
    _reset()
