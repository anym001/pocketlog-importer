"""Internal scheduler: run the pipeline on a cron schedule.

The scheduler is only the container's foreground process. The pipeline run
itself is an ordinary function, so it can equally be triggered on demand via
``docker exec <container> pocketlog-import --once`` (e.g. from an Unraid User
Script). SIGTERM is handled for a clean container stop.
"""

from __future__ import annotations

import signal
import threading
from datetime import datetime

from croniter import croniter

from .config import AppConfig
from .logging_config import get_logger
from .pipeline import run
from .rules import Rule

log = get_logger("scheduler")


def run_scheduler(config: AppConfig, rules: list[Rule]) -> None:
    stop = threading.Event()

    def _handle_signal(signum, _frame):
        log.info("Received signal %s — shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    cron = config.schedule.cron
    if not croniter.is_valid(cron):
        raise ValueError(f"invalid cron expression: {cron!r}")

    log.info("Scheduler started with cron %r", cron)
    # Run once immediately on startup, then follow the schedule.
    _safe_run(config, rules)

    itr = croniter(cron, datetime.now())
    while not stop.is_set():
        next_run = itr.get_next(datetime)
        wait = (next_run - datetime.now()).total_seconds()
        if wait > 0:
            # Wake early on stop; loop re-checks the time otherwise.
            if stop.wait(timeout=wait):
                break
        _safe_run(config, rules)

    log.info("Scheduler stopped")


def _safe_run(config: AppConfig, rules: list[Rule]) -> None:
    try:
        run(config, rules, dry_run=config.options.dry_run)
    except Exception:  # noqa: BLE001 - the scheduler must keep running
        log.exception("Scheduled run failed")
