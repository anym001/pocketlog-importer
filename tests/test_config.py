import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from bank_importer.config import load_config, validate_config

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
    monkeypatch.setenv("NOTIFY_TOKEN", "pb_from_env")
    config = load_config(_write(tmp_path))
    assert config.pocketlog.api_key == "plk_from_env"
    assert config.pocketlog.base_url == "https://override.example.com"
    assert config.notify.token == "pb_from_env"


def test_notify_defaults_off(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTIFY_TOKEN", raising=False)
    config = load_config(_write(tmp_path))
    assert config.notify.url is None
    assert config.notify.events == "problems"
    assert config.notify.token is None


def test_missing_required_field(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("schedule:\n  cron: '* * * * *'\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(cfg)


def test_malformed_yaml_raises_value_error(tmp_path):
    # A YAML syntax error must surface as ValueError (clean CLI message),
    # not an opaque yaml.YAMLError traceback.
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("pocketlog: [unterminated\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(cfg)


def _config(tmp_path, monkeypatch, extra="", *, api_key=None):
    monkeypatch.delenv("POCKETLOG_API_KEY", raising=False)
    monkeypatch.delenv("POCKETLOG_BASE_URL", raising=False)
    monkeypatch.delenv("NOTIFY_TOKEN", raising=False)
    if api_key:
        monkeypatch.setenv("POCKETLOG_API_KEY", api_key)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_YAML + extra, encoding="utf-8")
    return load_config(cfg)


def test_validate_ok_dry_run(tmp_path, monkeypatch):
    # Default _YAML is dry_run + no API key + no banks: valid in dry-run.
    config = _config(tmp_path, monkeypatch)
    validate_config(config, dry_run=True)  # does not raise


def test_validate_invalid_cron(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    config.schedule.cron = "not a cron"
    with pytest.raises(ValueError, match="cron"):
        validate_config(config, dry_run=True)


def test_validate_missing_api_key_real_run(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="POCKETLOG_API_KEY"):
        validate_config(config, dry_run=False)


def test_validate_api_key_present_real_run(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch, api_key="plk_real")
    validate_config(config, dry_run=False)  # does not raise


def test_validate_unknown_parser(tmp_path, monkeypatch):
    extra = '\nbanks:\n  - match: "*.csv"\n    parser: nonsense\n'
    config = _config(tmp_path, monkeypatch, extra)
    with pytest.raises(ValueError, match="unknown parser"):
        validate_config(config, dry_run=True)


def test_validate_known_parser(tmp_path, monkeypatch):
    extra = '\nbanks:\n  - match: "EASYBANK_*.csv"\n    parser: easybank\n'
    config = _config(tmp_path, monkeypatch, extra)
    validate_config(config, dry_run=True)  # does not raise


def test_validate_warns_empty_banks(tmp_path, monkeypatch, caplog):
    config = _config(tmp_path, monkeypatch)
    with caplog.at_level(logging.WARNING, logger="bank_importer.config"):
        validate_config(config, dry_run=True)
    assert any("No bank mappings" in r.message for r in caplog.records)


def test_validate_warns_notify_url_without_token_in_dry_run(
    tmp_path, monkeypatch, caplog
):
    extra = "\nnotify:\n  url: https://push.example.com\n"
    config = _config(tmp_path, monkeypatch, extra)
    with caplog.at_level(logging.WARNING, logger="bank_importer.config"):
        validate_config(config, dry_run=True)
    assert any("NOTIFY_TOKEN" in r.message for r in caplog.records)
