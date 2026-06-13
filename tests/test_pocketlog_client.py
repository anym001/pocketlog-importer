import httpx
import pytest

from pocketlog_importer.exporters import PocketLogClient
from pocketlog_importer.exporters.pocketlog import PocketLogError


def _client(handler, **kwargs) -> PocketLogClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    # backoff_base=0 keeps the retry tests instant (sleep(0) between attempts).
    kwargs.setdefault("backoff_base", 0)
    return PocketLogClient("https://pl.example.com", "plk_test", client=http, **kwargs)


def test_import_success_parses_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/import/csv"
        assert request.headers["Authorization"] == "Bearer plk_test"
        assert b"date;type;amount" in request.content
        return httpx.Response(
            200, json={"imported": 3, "skipped": 0, "deduped": 1, "errors": []}
        )

    result = _client(handler).import_csv(
        b"date;type;amount;description;category;tags\n"
    )
    assert result.imported == 3
    assert result.deduped == 1


def test_import_error_status_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "insufficient_scope"})

    with pytest.raises(PocketLogError) as exc:
        _client(handler).import_csv(b"x")
    assert "403" in str(exc.value)
    assert "insufficient_scope" in str(exc.value)


def test_missing_api_key_rejected():
    with pytest.raises(ValueError):
        PocketLogClient("https://pl.example.com", "")


def test_transient_failures_are_retried_until_success():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused", request=request)
        if len(calls) == 2:
            return httpx.Response(503, text="restarting")
        return httpx.Response(
            200, json={"imported": 1, "skipped": 0, "deduped": 0, "errors": []}
        )

    result = _client(handler).import_csv(b"x")
    assert result.imported == 1
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(PocketLogError) as exc:
        _client(handler, max_attempts=3).import_csv(b"x")
    assert "after 3 attempts" in str(exc.value)
    assert len(calls) == 3


def test_permanent_4xx_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403, json={"detail": "insufficient_scope"})

    with pytest.raises(PocketLogError):
        _client(handler).import_csv(b"x")
    assert len(calls) == 1


def test_rate_limit_429_is_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(
            200, json={"imported": 0, "skipped": 0, "deduped": 1, "errors": []}
        )

    result = _client(handler).import_csv(b"x")
    assert result.deduped == 1
    assert len(calls) == 2
