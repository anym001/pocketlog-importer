"""Contract tests against a real PocketLog instance.

They pin the importer's integration boundary (CLAUDE.md, "PocketLog import
contract") against the actual server implementation:

  * full pipeline run: parse -> rules -> serialize -> POST /api/import/csv,
    verified back through PocketLog's own CSV export
  * idempotency: a re-run of the same bank files only dedups
  * per-row error format: ``errors: [{row, code, params}]`` with the stable
    codes the importer surfaces in its logs
  * auth semantics: insufficient scope -> 403, unknown key -> 401
"""

from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path

import httpx
import pytest

from pocketlog_importer.config import AppConfig, PathsConfig, PocketLogConfig
from pocketlog_importer.exporters import PocketLogClient
from pocketlog_importer.exporters.pocketlog import PocketLogError
from pocketlog_importer.pipeline import run
from pocketlog_importer.rules import compile_rules

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# Rules covering the bank sample fixtures; ONLINESHOP is deliberately left
# out so exactly one dadat booking exercises the unmatched review path.
CONTRACT_RULES = compile_rules(
    [
        {
            "match": "STREAMINGCO",
            "description": "Streaming Service",
            "category": "Entertainment",
            "tags": ["subscription"],
        },
        {
            "match": "MOBILECARRIER",
            "description": "Mobile plan",
            "category": "Internet",
            "tags": ["recurring"],
        },
        {
            "match": "ELECTRICITYCO",
            "description": "Electricity",
            "category": "Housing",
            "tags": ["recurring"],
        },
        {
            "match": "RENTINGCO",
            "description": "Rent",
            "category": "Housing",
            "tags": ["recurring", "rent"],
        },
        {
            "match": "BANKOMAT|Debitkartenbeheb",
            "description": "Cash withdrawal",
            "category": "Cash",
            "tags": ["cash"],
        },
    ]
)

EXPECTED_MATCHED = 7  # 5 easybank + 2 dadat bookings
EXPECTED_UNMATCHED = 1  # the ONLINESHOP booking

PROBE_CSV = (
    b"date;type;amount;description;category;tags\n"
    b"2026-06-01;out;1.00;scope probe;Probe;\n"
)


def _make_config(tmp_path: Path, base_url: str, api_key: str) -> AppConfig:
    return AppConfig(
        pocketlog=PocketLogConfig(base_url=base_url, api_key=api_key),
        paths=PathsConfig(
            input=tmp_path / "input",
            processed=tmp_path / "processed",
            failed=tmp_path / "failed",
            output=tmp_path / "output",
        ),
    )


def _stage_inputs(input_dir: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        FIXTURES / "easybank_sample.csv", input_dir / "EASYBANK_Umsatzliste_1.csv"
    )
    shutil.copy(FIXTURES / "dadat_sample.csv", input_dir / "umsaetzegirokonto_1.csv")


def _export_rows(admin_session: httpx.Client) -> list[dict]:
    resp = admin_session.get("/api/export/csv")
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.text), delimiter=";"))


def test_pipeline_import_and_idempotency(
    tmp_path: Path,
    pocketlog_base_url: str,
    import_api_key: str,
    admin_session: httpx.Client,
) -> None:
    config = _make_config(tmp_path, pocketlog_base_url, import_api_key)
    _stage_inputs(config.paths.input)

    summary = run(config, CONTRACT_RULES)

    assert summary.failed_files == []
    assert summary.files == 2
    assert summary.parsed == EXPECTED_MATCHED + EXPECTED_UNMATCHED
    assert summary.matched == summary.imported == EXPECTED_MATCHED
    assert summary.unmatched == EXPECTED_UNMATCHED
    assert summary.deduped == 0

    # Originals are archived per run, the unmatched booking lands in the
    # review CSV — nothing stays behind in input/.
    assert list(config.paths.input.glob("*.csv")) == []
    assert len(list(config.paths.processed.glob("*/*.csv"))) == 2
    unmatched_files = list(config.paths.output.glob("*.unmatched.csv"))
    assert len(unmatched_files) == 1
    unmatched_rows = list(
        csv.DictReader(
            io.StringIO(unmatched_files[0].read_text("utf-8")), delimiter=";"
        )
    )
    assert len(unmatched_rows) == 1
    assert "ONLINESHOP" in unmatched_rows[0]["raw_text"]

    # Server state via PocketLog's own export: amounts, direction, dates and
    # the rule-enriched categories/tags arrived (auto-created on the fly).
    rows = _export_rows(admin_session)
    assert len(rows) == EXPECTED_MATCHED

    rent = sorted(
        (r for r in rows if r["description"] == "Rent"), key=lambda r: r["amount"]
    )
    assert [r["amount"] for r in rent] == ["47.50", "783.65"]
    for r in rent:
        assert (r["type"], r["date"], r["category"]) == ("out", "2026-06-05", "Housing")
        assert set(r["tags"].split(",")) == {"recurring", "rent"}

    cash = [r for r in rows if r["description"] == "Cash withdrawal"]
    assert {r["date"] for r in cash} == {"2026-05-15", "2026-05-11"}
    assert all(r["amount"] == "200.00" and r["category"] == "Cash" for r in cash)

    (streaming,) = [r for r in rows if r["description"] == "Streaming Service"]
    assert (streaming["date"], streaming["type"], streaming["amount"]) == (
        "2026-06-08",
        "out",
        "13.99",
    )
    assert streaming["tags"] == "subscription"

    # Idempotency: the same bank files land in input/ again (e.g. a second
    # export) — the server-side dedup hash absorbs every known row, which is
    # why the importer needs no dedup state of its own.
    _stage_inputs(config.paths.input)
    summary2 = run(config, CONTRACT_RULES)

    assert summary2.imported == 0
    assert summary2.deduped == EXPECTED_MATCHED
    assert summary2.unmatched == EXPECTED_UNMATCHED
    assert len(_export_rows(admin_session)) == EXPECTED_MATCHED


def test_per_row_error_format(pocketlog_base_url: str, import_api_key: str) -> None:
    # Only the codes the importer actually surfaces in its logs are pinned;
    # the full catalogue is PocketLog's own concern.
    broken = (
        b"date;type;amount;description;category;tags\n"
        b"2026-13-45;out;9.99;broken date;Probe;\n"
        b"2026-06-01;out;not-a-number;broken amount;Probe;\n"
    )
    with PocketLogClient(pocketlog_base_url, import_api_key) as client:
        result = client.import_csv(broken, filename="broken.csv")

    assert result.imported == 0
    assert result.skipped == 2
    assert [(e["row"], e["code"]) for e in result.errors] == [
        (2, "date_unrecognised"),
        (3, "amount_unrecognised"),
    ]
    assert result.errors[0]["params"] == {"value": "2026-13-45"}
    assert result.errors[1]["params"] == {"value": "not-a-number"}


def test_insufficient_scope_is_403(pocketlog_base_url: str, make_api_key) -> None:
    read_key = make_api_key("contract-read-only", ["read"])
    with PocketLogClient(pocketlog_base_url, read_key) as client:
        with pytest.raises(PocketLogError, match="HTTP 403"):
            client.import_csv(PROBE_CSV)


def test_unknown_key_is_401(pocketlog_base_url: str) -> None:
    with PocketLogClient(pocketlog_base_url, "plk_" + "0" * 43) as client:
        with pytest.raises(PocketLogError, match="HTTP 401"):
            client.import_csv(PROBE_CSV)
