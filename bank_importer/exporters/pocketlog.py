"""Serialize transactions to PocketLog CSV and import them via the API.

PocketLog import contract (see PocketLog ``routers/imexport.py``):
  * ``POST /api/import/csv``, multipart field ``file``
  * Auth: ``Authorization: Bearer plk_...`` with ``import`` scope
  * Columns: ``date;type;amount;description;category;tags`` (``;``, UTF-8)
  * ``amount`` always positive; direction is in ``type`` (``in``/``out``)
  * Response: ``{imported, skipped, deduped, errors:[{row,code,params}]}``
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx

from ..models import NormalizedTransaction
from ..parsing import guard_csv_field

CSV_HEADER = ["date", "type", "amount", "description", "category", "tags"]
UNMATCHED_CSV_HEADER = ["date", "type", "amount", "raw_text"]
_IMPORT_PATH = "/api/import/csv"


def _amount_str(amount: Decimal) -> str:
    return f"{amount:.2f}" if isinstance(amount, Decimal) else str(amount)


def _format_row(tx: NormalizedTransaction) -> list[str]:
    return [
        tx.date.isoformat() if isinstance(tx.date, date) else str(tx.date),
        tx.type,
        _amount_str(tx.amount),
        guard_csv_field(tx.description),
        guard_csv_field(tx.category or ""),
        ",".join(guard_csv_field(t) for t in tx.tags),
    ]


def serialize_csv(transactions: list[NormalizedTransaction]) -> bytes:
    """Serialize transactions into PocketLog-compatible CSV bytes (UTF-8)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for tx in transactions:
        writer.writerow(_format_row(tx))
    return buffer.getvalue().encode("utf-8")


def serialize_unmatched(transactions: list[NormalizedTransaction]) -> bytes:
    """Serialize unmatched bookings into the review CSV bytes (UTF-8).

    The ``*.unmatched.csv`` files are meant to be opened in a spreadsheet for
    review, and ``raw_text`` is foreign bank text — so it gets the same
    formula-injection guard as the export columns.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(UNMATCHED_CSV_HEADER)
    for tx in transactions:
        writer.writerow(
            [
                tx.date.isoformat(),
                tx.type,
                _amount_str(tx.amount),
                guard_csv_field(tx.raw_text),
            ]
        )
    return buffer.getvalue().encode("utf-8")


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    deduped: int = 0
    errors: list[dict] = field(default_factory=list)

    @classmethod
    def from_response(cls, data: dict) -> ImportResult:
        return cls(
            imported=data.get("imported", 0),
            skipped=data.get("skipped", 0),
            deduped=data.get("deduped", 0),
            errors=data.get("errors", []),
        )


class PocketLogError(RuntimeError):
    """Raised when the import endpoint returns a non-success status."""


class PocketLogClient:
    """Thin HTTP client around PocketLog's CSV import endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        verify_tls: bool = True,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for a real import")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.Client(verify=verify_tls, timeout=timeout)

    def import_csv(
        self, csv_bytes: bytes, filename: str = "import.csv"
    ) -> ImportResult:
        response = self._client.post(
            self._base_url + _IMPORT_PATH,
            files={"file": (filename, csv_bytes, "text/csv")},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if response.status_code == 200:
            return ImportResult.from_response(response.json())
        # Surface the common, actionable failure modes with a clear message.
        detail = _safe_detail(response)
        raise PocketLogError(f"import failed: HTTP {response.status_code} ({detail})")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PocketLogClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _safe_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("detail", body))
        return str(body)
    except ValueError:
        return response.text[:200]
