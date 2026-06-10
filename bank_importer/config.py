"""Configuration loading and validation (pydantic v2).

The runtime config lives in ``/config/config.yaml`` (mounted), the rules in
``/config/rules.yaml``. Secrets are taken from the environment, never the YAML:
``POCKETLOG_API_KEY`` is required for a real (non-dry-run) import.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class PocketLogConfig(BaseModel):
    base_url: str
    verify_tls: bool = True
    # Populated from POCKETLOG_API_KEY at load time; never stored in YAML.
    api_key: str | None = None


class ScheduleConfig(BaseModel):
    cron: str = "0 * * * *"  # hourly


class PathsConfig(BaseModel):
    input: Path = Path("/data/input")
    processed: Path = Path("/data/processed")
    failed: Path = Path("/data/failed")
    output: Path = Path("/data/output")


class BankMapping(BaseModel):
    match: str  # filename glob, e.g. "EASYBANK_*.csv"
    parser: str  # registered parser name


class Options(BaseModel):
    dry_run: bool = False


class AppConfig(BaseModel):
    pocketlog: PocketLogConfig
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    banks: list[BankMapping] = Field(default_factory=list)
    options: Options = Field(default_factory=Options)
    rules_file: Path = Path("/config/rules.yaml")


def load_config(path: str | Path) -> AppConfig:
    """Load and validate ``config.yaml``, merging environment overrides."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    config = AppConfig.model_validate(data)

    # Environment overrides (secrets + optional convenience overrides).
    api_key = os.getenv("POCKETLOG_API_KEY")
    if api_key:
        config.pocketlog.api_key = api_key
    base_url = os.getenv("POCKETLOG_BASE_URL")
    if base_url:
        config.pocketlog.base_url = base_url

    return config
