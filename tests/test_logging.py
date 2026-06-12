import logging

from bank_importer.logging_config import LOGGER_NAME, configure_logging, safe


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
    forged = "real.csv\n2099-01-01 00:00:00 ERROR bank_importer forged event"
    out = safe(forged)
    assert "\n" not in out and "\r" not in out
