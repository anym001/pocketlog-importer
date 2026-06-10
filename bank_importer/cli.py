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
        "--version", action="version", version=f"pocketlog-import {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = configure_logging()

    try:
        config = load_config(args.config)
        rules = load_rules(config.rules_file)
    except (OSError, ValueError) as exc:
        log.error("Configuration error: %s", exc)
        return 2

    log.info("pocketlog-import %s starting (rules: %d)", __version__, len(rules))

    if args.once:
        dry_run = args.dry_run or config.options.dry_run
        from .pipeline import run

        run(config, rules, dry_run=dry_run)
        return 0

    if args.dry_run:
        config.options.dry_run = True
    from .scheduler import run_scheduler

    run_scheduler(config, rules)
    return 0


if __name__ == "__main__":
    sys.exit(main())
