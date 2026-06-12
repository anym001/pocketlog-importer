import json

import httpx
import pytest

from bank_importer.config import NotifyConfig
from bank_importer.notify import (
    PRIORITY_INFO,
    PRIORITY_PROBLEM,
    GotifyNotifier,
    Notification,
    build_notifier,
    compose_crash_message,
    compose_run_message,
    notify_crash,
    notify_run,
)
from bank_importer.pipeline import RunSummary

_NOTE = Notification("t", "m", PRIORITY_INFO, False)


def _notifier(handler) -> GotifyNotifier:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return GotifyNotifier("https://push.example.com", "pb_token", client=http)


class _Recorder:
    """Stands in for GotifyNotifier in the dispatch tests."""

    def __init__(self):
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> bool:
        self.sent.append(notification)
        return True


def test_send_posts_gotify_message():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["token"] = request.url.params.get("token")
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"id": 1})

    assert _notifier(handler).send(
        Notification("Bank import: OK", "imported: 3", PRIORITY_INFO, False)
    )
    assert seen["path"] == "/message"
    assert seen["token"] == "pb_token"
    assert seen["body"] == {
        "title": "Bank import: OK",
        "message": "imported: 3",
        "priority": PRIORITY_INFO,
    }


def test_send_is_best_effort_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    assert _notifier(handler).send(_NOTE) is False


def test_send_is_best_effort_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert _notifier(handler).send(_NOTE) is False


def test_build_notifier_off_without_url():
    assert build_notifier(NotifyConfig()) is None


def test_build_notifier_requires_token():
    with pytest.raises(ValueError, match="NOTIFY_TOKEN"):
        build_notifier(NotifyConfig(url="https://push.example.com"))


def test_compose_skips_idle_run():
    assert compose_run_message(RunSummary()) is None


def test_compose_clean_run():
    summary = RunSummary(files=2, parsed=8, matched=8, imported=8)
    note = compose_run_message(summary)
    assert note is not None
    assert note.problem is False
    assert note.priority == PRIORITY_INFO
    assert "imported: 8" in note.message


def test_compose_problem_run():
    summary = RunSummary(
        files=2,
        parsed=8,
        matched=6,
        imported=6,
        unmatched=2,
        failed_files=["broken.csv"],
    )
    note = compose_run_message(summary)
    assert note is not None
    assert note.problem is True
    assert note.priority == PRIORITY_PROBLEM
    assert "unmatched: 2" in note.message
    assert "failed: broken.csv" in note.message


def test_compose_crash_message():
    note = compose_crash_message(RuntimeError("boom"))
    assert note.problem is True
    assert note.priority == PRIORITY_PROBLEM
    assert "RuntimeError: boom" in note.message


def test_notify_run_problems_mode_suppresses_clean_runs():
    recorder = _Recorder()
    notify_run(recorder, "problems", RunSummary(files=1, imported=1))
    assert recorder.sent == []
    notify_run(recorder, "problems", RunSummary(files=1, unmatched=1))
    assert len(recorder.sent) == 1


def test_notify_run_always_mode_reports_clean_runs_but_not_idle():
    recorder = _Recorder()
    notify_run(recorder, "always", RunSummary(files=1, imported=1))
    assert len(recorder.sent) == 1
    notify_run(recorder, "always", RunSummary())
    assert len(recorder.sent) == 1


def test_dispatch_is_noop_without_notifier():
    notify_run(None, "always", RunSummary(files=1, imported=1))
    notify_crash(None, RuntimeError("boom"))
