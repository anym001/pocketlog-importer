"""Command-line entry point.

Default (no ``--once``): start the internal scheduler (container foreground
process). ``--once`` runs the pipeline a single time and exits — the path used
by ``docker exec`` / Unraid User Scripts. ``--dry-run`` writes CSVs but skips
the API import.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import load_config
from .logging_config import configure_logging
from .notify import build_notifier, notify_run
from .rules import load_rules

DEFAULT_CONFIG = "/config/config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pocketlog-import",
        description="Import bank CSV exports into PocketLog.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"path to config.yaml (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="process the input directory once and exit (no scheduler)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write output CSVs but do not import via the API",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="exit 0 if the run heartbeat is fresh for the cron schedule, else 1",
    )
    parser.add_argument(
        "--version", action="version", version=f"pocketlog-import {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = configure_logging()

    if args.healthcheck:
        return _healthcheck(args.config)

    try:
        config = load_config(args.config)
        rules = load_rules(config.rules_file)
        # CLI flag wins over config; merge once so both run modes read one
        # value. Dry-run never notifies — its point is "no side effects".
        config.options.dry_run = args.dry_run or config.options.dry_run
        notifier = None if config.options.dry_run else build_notifier(config.notify)
    except (OSError, ValueError) as exc:
        log.error("Configuration error: %s", exc)
        return 2

    log.info("pocketlog-import %s starting (rules: %d)", __version__, len(rules))

    if args.once:
        from .pipeline import run

        summary = run(config, rules, dry_run=config.options.dry_run)
        notify_run(notifier, config.notify.events, summary)
        return 0

    from .scheduler import run_scheduler

    run_scheduler(config, rules, notifier=notifier)
    return 0


def _healthcheck(config_path: str) -> int:
    """Docker HEALTHCHECK entry: stdout status line + exit code, no logging."""
    from .health import check_heartbeat
    from .pipeline import heartbeat_path

    try:
        config = load_config(config_path)
        healthy, reason = check_heartbeat(heartbeat_path(config), config.schedule.cron)
    except (OSError, ValueError) as exc:
        print(f"unhealthy: {exc}")
        return 1
    print(("healthy: " if healthy else "unhealthy: ") + reason)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
