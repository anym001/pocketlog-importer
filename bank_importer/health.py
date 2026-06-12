"""Container health: is the scheduler still producing heartbeats?

``pipeline.run()`` touches the heartbeat file after every run (idle runs
included), so a fresh heartbeat means the scheduler loop is alive. "Fresh" is
derived from the configured cron instead of a magic number: twice the gap
between the two most recent scheduled ticks, with a floor for very tight
crons — hourly and daily schedules both get a sensible threshold without any
extra configuration.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from croniter import croniter

# A run may legitimately straddle one tick (large import, API retries); only
# a missed second tick signals a wedged scheduler.
_INTERVAL_FACTOR = 2.0
# Floor for very tight crons (e.g. ``* * * * *``) so jitter never flaps health.
_MIN_MAX_AGE = 300.0


def max_heartbeat_age(cron: str, *, now: datetime | None = None) -> float:
    """Allowed heartbeat age in seconds, derived from the cron schedule."""
    itr = croniter(cron, now or datetime.now())
    prev1 = itr.get_prev(datetime)
    prev2 = itr.get_prev(datetime)
    interval = (prev1 - prev2).total_seconds()
    return max(interval * _INTERVAL_FACTOR, _MIN_MAX_AGE)


def check_heartbeat(
    heartbeat: Path, cron: str, *, now: float | None = None
) -> tuple[bool, str]:
    """Return ``(healthy, reason)`` for the heartbeat file."""
    if now is None:
        now = time.time()
    try:
        last_run = int(heartbeat.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return False, f"no heartbeat yet ({heartbeat})"
    except (OSError, ValueError) as exc:
        return False, f"unreadable heartbeat: {exc}"
    age = now - last_run
    allowed = max_heartbeat_age(cron)
    status = f"heartbeat is {age:.0f}s old (allowed: {allowed:.0f}s)"
    return age <= allowed, status
