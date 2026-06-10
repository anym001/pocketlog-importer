from pathlib import Path

import pytest
from pydantic import ValidationError

from bank_importer.config import load_config

_YAML = """
pocketlog:
  base_url: https://pocketlog.example.com
  verify_tls: false
schedule:
  cron: "*/15 * * * *"
paths:
  input: /tmp/in
options:
  dry_run: true
rules_file: /tmp/rules.yaml
"""


def _write(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_YAML, encoding="utf-8")
    return cfg


def test_load_config(tmp_path, monkeypatch):
    monkeypatch.delenv("POCKETLOG_API_KEY", raising=False)
    monkeypatch.delenv("POCKETLOG_BASE_URL", raising=False)
    config = load_config(_write(tmp_path))
    assert config.pocketlog.base_url == "https://pocketlog.example.com"
    assert config.pocketlog.verify_tls is False
    assert config.schedule.cron == "*/15 * * * *"
    assert config.paths.input == Path("/tmp/in")
    assert config.options.dry_run is True
    assert config.pocketlog.api_key is None


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("POCKETLOG_API_KEY", "plk_from_env")
    monkeypatch.setenv("POCKETLOG_BASE_URL", "https://override.example.com")
    config = load_config(_write(tmp_path))
    assert config.pocketlog.api_key == "plk_from_env"
    assert config.pocketlog.base_url == "https://override.example.com"


def test_missing_required_field(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("schedule:\n  cron: '* * * * *'\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(cfg)
