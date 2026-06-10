import httpx
import pytest

from bank_importer.exporters import PocketLogClient
from bank_importer.exporters.pocketlog import PocketLogError


def _client(handler) -> PocketLogClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return PocketLogClient("https://pl.example.com", "plk_test", client=http)


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
