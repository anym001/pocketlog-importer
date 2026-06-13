"""Configuration loading and validation (pydantic v2).

The runtime config lives in ``/config/config.yaml`` (mounted), the rules in
``/config/rules.yaml``. Secrets are taken from the environment, never the YAML:
``POCKETLOG_API_KEY`` is required for a real (non-dry-run) import.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class PocketLogConfig(BaseModel):
    base_url: str
    verify_tls: bool = True
    # Populated from POCKETLOG_API_KEY at load time; never stored in YAML.
    api_key: str | None = None


class NotifyConfig(BaseModel):
    """Push notifications for run outcomes. Off unless ``url`` is set."""

    # "gotify" covers every Gotify-compatible endpoint, including PushBits.
    type: Literal["gotify"] = "gotify"
    url: str | None = None
    # "problems" = only failed/unmatched runs and crashes; "always" also
    # reports clean runs (idle runs without input files never notify).
    events: Literal["problems", "always"] = "problems"
    verify_tls: bool = True
    # Populated from NOTIFY_TOKEN at load time; never stored in YAML.
    token: str | None = None


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
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    rules_file: Path = Path("/config/rules.yaml")


def load_config(path: str | Path) -> AppConfig:
    """Load and validate ``config.yaml``, merging environment overrides."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        # Re-raise as ValueError so the CLI reports it as a clean
        # "Configuration error" (exit 2) instead of an opaque traceback.
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    config = AppConfig.model_validate(data)

    # Environment overrides (secrets + optional convenience overrides).
    api_key = os.getenv("POCKETLOG_API_KEY")
    if api_key:
        config.pocketlog.api_key = api_key
    base_url = os.getenv("POCKETLOG_BASE_URL")
    if base_url:
        config.pocketlog.base_url = base_url
    notify_token = os.getenv("NOTIFY_TOKEN")
    if notify_token:
        config.notify.token = notify_token

    return config


def validate_config(config: AppConfig, *, dry_run: bool) -> None:
    """Check cross-field config semantics beyond pydantic's per-field rules.

    Pydantic validates the shape of each field; this validates how the fields
    work together at runtime. Fatal misconfigurations raise ``ValueError`` (the
    CLI turns these into a clean "Configuration error" + exit 2). Settings that
    are suspicious but still workable are logged as warnings and never abort the
    run.
    """
    from croniter import croniter

    from .logging_config import get_logger
    from .parsers import available_parsers

    log = get_logger("config")

    # --- Fatal: the run cannot do its job with these ---------------------
    if not croniter.is_valid(config.schedule.cron):
        raise ValueError(f"invalid cron expression: {config.schedule.cron!r}")

    if not dry_run and not config.pocketlog.api_key:
        raise ValueError(
            "POCKETLOG_API_KEY is required for a real import "
            "(set the environment variable, or use --dry-run)"
        )

    known = available_parsers()
    for mapping in config.banks:
        if mapping.parser not in known:
            raise ValueError(
                f"bank mapping {mapping.match!r} references unknown parser "
                f"{mapping.parser!r} (available: {', '.join(sorted(known))})"
            )

    # --- Non-fatal: still works, but worth flagging ----------------------
    if not config.banks:
        log.warning(
            "No bank mappings configured — the parser is auto-detected per "
            "file by content sniffing"
        )
    if dry_run and config.notify.url and not config.notify.token:
        # In a real run this is fatal (build_notifier raises); in dry-run the
        # notifier is never built, so only surface it as a warning here.
        log.warning(
            "notify.url is set but NOTIFY_TOKEN is missing — notifications "
            "would be disabled outside dry-run"
        )
