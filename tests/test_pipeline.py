import shutil
from pathlib import Path

from bank_importer import pipeline
from bank_importer.config import AppConfig, PathsConfig, PocketLogConfig
from bank_importer.exporters.pocketlog import ImportResult
from bank_importer.rules import compile_rules

FIXTURES = Path(__file__).parent / "fixtures"


def _config(tmp_path: Path, dry_run: bool = True) -> AppConfig:
    return AppConfig(
        pocketlog=PocketLogConfig(base_url="https://pl.example.com", api_key="plk_x"),
        paths=PathsConfig(
            input=tmp_path / "input",
            processed=tmp_path / "processed",
            failed=tmp_path / "failed",
            output=tmp_path / "output",
        ),
    )


def _rules():
    return compile_rules(
        [{"match": "MUSIKBEISPIEL", "description": "Musikbeispiel", "category": "Freizeit"}]
    )


def _seed(tmp_path: Path, fixture: str, name: str) -> None:
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / fixture, tmp_path / "input" / name)


def test_dry_run_writes_csvs_and_archives(tmp_path):
    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")
    summary = pipeline.run(_config(tmp_path), _rules(), dry_run=True)

    assert summary.files == 1
    assert summary.parsed == 5
    assert summary.matched == 1  # only the Musikbeispiel row matches
    assert summary.unmatched == 4
    assert summary.imported == 0  # dry-run: no API call

    output = tmp_path / "output"
    matched_csv = list(output.glob("easybank-*.csv"))
    unmatched_csv = list(output.glob("*.unmatched.csv"))
    assert len(matched_csv) == 1
    assert len(unmatched_csv) == 1

    # Original moved to processed/, input emptied.
    assert not list((tmp_path / "input").glob("*.csv"))
    assert len(list((tmp_path / "processed").glob("*EASYBANK_x.csv"))) == 1


def test_real_run_pushes_and_counts(tmp_path, monkeypatch):
    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")

    pushed = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def import_csv(self, csv_bytes, filename="import.csv"):
            pushed["bytes"] = csv_bytes
            return ImportResult(imported=1, deduped=0, skipped=0, errors=[])

        def close(self):
            pass

    monkeypatch.setattr(pipeline, "PocketLogClient", FakeClient)
    summary = pipeline.run(_config(tmp_path, dry_run=False), _rules(), dry_run=False)

    assert summary.imported == 1
    assert b"Musikbeispiel" in pushed["bytes"]


def test_unparseable_file_goes_to_failed(tmp_path):
    (tmp_path / "input").mkdir(parents=True)
    (tmp_path / "input" / "mystery.csv").write_text("foo,bar,baz\n1,2,3\n")
    summary = pipeline.run(_config(tmp_path), _rules(), dry_run=True)

    assert summary.failed_files == ["mystery.csv"]
    assert len(list((tmp_path / "failed").glob("*mystery.csv"))) == 1


def test_no_input_is_noop(tmp_path):
    summary = pipeline.run(_config(tmp_path), _rules(), dry_run=True)
    assert summary.files == 0
    assert (tmp_path / ".last_run").exists()
