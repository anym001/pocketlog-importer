import time
from datetime import datetime
from pathlib import Path

from pocketlog_importer.cli import main
from pocketlog_importer.health import check_heartbeat, max_heartbeat_age

_NOW = datetime(2026, 6, 12, 12, 30)


def test_max_age_follows_the_cron_interval():
    # Hourly schedule: two ticks are 3600 s apart -> 7200 s allowed.
    assert max_heartbeat_age("0 * * * *", now=_NOW) == 7200.0
    # Daily schedule -> two days allowed.
    assert max_heartbeat_age("0 6 * * *", now=_NOW) == 2 * 86400.0


def test_max_age_has_a_floor_for_tight_crons():
    assert max_heartbeat_age("* * * * *", now=_NOW) == 300.0


def _write_heartbeat(path: Path, age_seconds: int) -> Path:
    path.write_text(str(int(time.time()) - age_seconds), encoding="utf-8")
    return path


def test_fresh_heartbeat_is_healthy(tmp_path):
    hb = _write_heartbeat(tmp_path / ".last_run", age_seconds=60)
    healthy, reason = check_heartbeat(hb, "0 * * * *")
    assert healthy is True
    assert "allowed" in reason


def test_stale_heartbeat_is_unhealthy(tmp_path):
    hb = _write_heartbeat(tmp_path / ".last_run", age_seconds=8000)
    healthy, _ = check_heartbeat(hb, "0 * * * *")
    assert healthy is False


def test_missing_heartbeat_is_unhealthy(tmp_path):
    healthy, reason = check_heartbeat(tmp_path / ".last_run", "0 * * * *")
    assert healthy is False
    assert "no heartbeat" in reason


def test_garbage_heartbeat_is_unhealthy(tmp_path):
    hb = tmp_path / ".last_run"
    hb.write_text("not-a-timestamp", encoding="utf-8")
    healthy, reason = check_heartbeat(hb, "0 * * * *")
    assert healthy is False
    assert "unreadable" in reason


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "pocketlog:\n"
        "  base_url: https://pocketlog.example.com\n"
        "paths:\n"
        f"  input: {tmp_path / 'in'}\n",
        encoding="utf-8",
    )
    return cfg


def test_cli_healthcheck_exit_codes(tmp_path, capsys):
    cfg = _write_config(tmp_path)

    # No heartbeat yet -> unhealthy.
    assert main(["--healthcheck", "--config", str(cfg)]) == 1
    assert "unhealthy" in capsys.readouterr().out

    _write_heartbeat(tmp_path / ".last_run", age_seconds=60)
    assert main(["--healthcheck", "--config", str(cfg)]) == 0
    assert "healthy" in capsys.readouterr().out
