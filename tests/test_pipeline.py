import re
import shutil
from pathlib import Path

from pocketlog_importer import pipeline
from pocketlog_importer.config import AppConfig, PathsConfig, PocketLogConfig
from pocketlog_importer.exporters.pocketlog import ImportResult
from pocketlog_importer.rules import compile_rules

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
        [
            {
                "match": "STREAMINGCO",
                "description": "Streaming Service",
                "category": "Entertainment",
            }
        ]
    )


def _seed(tmp_path: Path, fixture: str, name: str) -> None:
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / fixture, tmp_path / "input" / name)


def test_dry_run_writes_csvs_and_archives(tmp_path):
    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")
    summary = pipeline.run(_config(tmp_path), _rules(), dry_run=True)

    assert summary.files == 1
    assert summary.parsed == 5
    assert summary.matched == 1  # only the STREAMINGCO row matches
    assert summary.unmatched == 4
    assert summary.imported == 0  # dry-run: no API call

    output = tmp_path / "output"
    matched_csv = list(output.glob("easybank-*.csv"))
    unmatched_csv = list(output.glob("*.unmatched.csv"))
    assert len(matched_csv) == 1
    assert len(unmatched_csv) == 1

    # Original moved to processed/<run-ts>/ with its name intact, input emptied.
    assert not list((tmp_path / "input").glob("*.csv"))
    archived = list((tmp_path / "processed").glob("*/EASYBANK_x.csv"))
    assert len(archived) == 1
    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", archived[0].parent.name)


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
    assert b"Streaming Service" in pushed["bytes"]


def test_unparseable_file_goes_to_failed(tmp_path):
    (tmp_path / "input").mkdir(parents=True)
    (tmp_path / "input" / "mystery.csv").write_text("foo,bar,baz\n1,2,3\n")
    summary = pipeline.run(_config(tmp_path), _rules(), dry_run=True)

    assert summary.failed_files == ["mystery.csv"]
    assert len(list((tmp_path / "failed").glob("*/mystery.csv"))) == 1


def test_no_input_is_noop(tmp_path):
    summary = pipeline.run(_config(tmp_path), _rules(), dry_run=True)
    assert summary.files == 0
    assert (tmp_path / ".last_run").exists()


def test_process_file_returns_counts(tmp_path):
    # _process_file is directly testable: it returns a FileResult instead of
    # mutating a shared summary. client=None == dry-run (no API import).
    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")
    path = tmp_path / "input" / "EASYBANK_x.csv"
    run_ts = pipeline._timestamp()
    result = pipeline._process_file(
        path, _config(tmp_path), _rules(), client=None, run_ts=run_ts
    )

    assert result.parsed == 5
    assert result.matched == 1
    assert result.unmatched == 4
    assert result.imported == 0
    assert result.failed is False


def test_summary_fold_aggregates_and_tracks_failures():
    summary = pipeline.RunSummary()
    summary.fold(pipeline.FileResult(parsed=3, matched=2, unmatched=1), "a.csv")
    summary.fold(pipeline.FileResult(failed=True), "b.csv")

    assert summary.parsed == 3
    assert summary.matched == 2
    assert summary.unmatched == 1
    assert summary.failed_files == ["b.csv"]


def test_reprocessing_same_filename_does_not_overwrite_processed(tmp_path):
    """Two runs of the same filename must produce two separate archived files."""
    rules = _rules()
    config = _config(tmp_path)

    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")
    pipeline.run(config, rules, dry_run=True)

    # Re-seed the same filename and run again.
    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")
    pipeline.run(config, rules, dry_run=True)

    archived = list((tmp_path / "processed").glob("*/EASYBANK_x.csv"))
    assert len(archived) == 2, (
        f"Expected 2 archived files, got {len(archived)}: {[str(f) for f in archived]}"
    )
    # Each run archives into its own directory.
    assert archived[0].parent != archived[1].parent


def test_archiving_keeps_original_filename(tmp_path):
    """Archiving never renames the file, only nests it in a run directory."""
    config = _config(tmp_path)
    rules = _rules()

    _seed(tmp_path, "easybank_sample.csv", "EASYBANK_x.csv")
    pipeline.run(config, rules, dry_run=True)

    # Move the archived original back to input/ (the debug workflow) and rerun.
    archived = next((tmp_path / "processed").glob("*/EASYBANK_x.csv"))
    archived.rename(tmp_path / "input" / archived.name)
    pipeline.run(config, rules, dry_run=True)

    names = {p.name for p in (tmp_path / "processed").glob("*/*.csv")}
    assert names == {"EASYBANK_x.csv"}
