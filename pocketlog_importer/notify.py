"""Run notifications via a Gotify-compatible push API (PushBits, Gotify).

PushBits (https://github.com/pushbits/server) relays messages into a Matrix
room and implements Gotify's message API: ``POST {url}/message?token=<token>``
with a JSON body ``{title, message, priority}``. The application token comes
from the ``NOTIFY_TOKEN`` environment variable, never from YAML, and is never
logged (it travels as a query parameter, so request URLs must not be logged
either).

Notifications are strictly best-effort: a failed send is logged and swallowed
— the import result never depends on the notifier. Message content is limited
to counters and filenames; booking data never leaves the machine this way.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import NotifyConfig
from .logging_config import get_logger, safe
from .pipeline import RunSummary

log = get_logger("notify")

_MESSAGE_PATH = "/message"

# Gotify priority scale (0-10); >= 8 is "high" and typically bypasses
# client-side muting, which is exactly right for failed runs.
PRIORITY_INFO = 4
PRIORITY_PROBLEM = 8


@dataclass
class Notification:
    title: str
    message: str
    priority: int
    problem: bool


class GotifyNotifier:
    """Minimal client for Gotify-compatible push endpoints."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        verify_tls: bool = True,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not token:
            raise ValueError("notify.url is set but NOTIFY_TOKEN is missing")
        self._url = url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(verify=verify_tls, timeout=timeout)
        log.debug("Notifier ready: %s (verify_tls=%s)", self._url, verify_tls)

    def send(self, notification: Notification) -> bool:
        """Push one message; best-effort (False + warning instead of raising)."""
        try:
            response = self._client.post(
                self._url + _MESSAGE_PATH,
                params={"token": self._token},
                json={
                    "title": notification.title,
                    "message": notification.message,
                    "priority": notification.priority,
                },
            )
        except httpx.HTTPError as exc:
            log.warning("Notification failed: %s", safe(exc))
            return False
        if response.status_code >= 400:
            log.warning("Notification failed: HTTP %d", response.status_code)
            return False
        log.info("Notification sent: %s", notification.title)
        return True

    def close(self) -> None:
        self._client.close()


def build_notifier(notify: NotifyConfig) -> GotifyNotifier | None:
    """Create the configured notifier, or None when notifications are off."""
    if not notify.url:
        return None
    return GotifyNotifier(notify.url, notify.token or "", verify_tls=notify.verify_tls)


def compose_run_message(summary: RunSummary) -> Notification | None:
    """Build the notification for a finished run.

    Returns None when there is nothing to report (no input files) — an idle
    scheduler tick must never page anyone, not even with ``events: always``.
    """
    if summary.files == 0:
        return None
    # Unmatched bookings are the expected steady state of a whitelist import
    # (anything without a rule is deliberately filtered out), so they are
    # reported as an info line but never flip a run to "problem". Only a
    # failed file (parse/import error) warrants the high-priority alert.
    problem = bool(summary.failed_files)
    lines = [
        f"files: {summary.files}",
        f"imported: {summary.imported}",
        f"deduped: {summary.deduped}",
    ]
    if summary.unmatched:
        lines.append(f"unmatched: {summary.unmatched} (review *.unmatched.csv)")
    if summary.failed_files:
        lines.append("failed: " + ", ".join(summary.failed_files))
    title = "Bank import: problems" if problem else "Bank import: OK"
    priority = PRIORITY_PROBLEM if problem else PRIORITY_INFO
    return Notification(title, "\n".join(lines), priority, problem)


def compose_crash_message(exc: Exception) -> Notification:
    """Build the notification for a run that died with an exception."""
    detail = f"{type(exc).__name__}: {exc}"[:300]
    return Notification("Bank import: run crashed", detail, PRIORITY_PROBLEM, True)


def notify_run(
    notifier: GotifyNotifier | None, events: str, summary: RunSummary
) -> None:
    """Send the run outcome according to the configured event filter."""
    if notifier is None:
        log.debug("Notifications disabled (no notifier configured)")
        return
    notification = compose_run_message(summary)
    if notification is None:
        log.debug("Notification skipped: no input files processed")
        return
    if events == "problems" and not notification.problem:
        log.debug("Notification skipped: events=problems but run was clean")
        return
    if not notifier.send(notification):
        log.warning("Run notification could not be delivered (see above for details)")


def notify_crash(notifier: GotifyNotifier | None, exc: Exception) -> None:
    """Send a crash alert; fires in every event mode."""
    if notifier is None:
        return
    if not notifier.send(compose_crash_message(exc)):
        log.warning("Crash notification could not be delivered (see above for details)")
