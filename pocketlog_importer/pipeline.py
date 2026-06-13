"""Pipeline orchestration: discover -> parse -> rules -> export -> archive.

A single ``run()`` processes every CSV in the input directory. It is guarded by
a file lock so a manual ``docker exec ... --once`` run never overlaps with a
scheduler tick. Re-runs are safe because PocketLog deduplicates imports and the
move into ``processed/`` is atomic.

Originals are archived under a per-run subdirectory
(``processed/<run-ts>/<original-name>`` resp. ``failed/<run-ts>/...``), so the
original filename is never rewritten and re-running a file can never overwrite
an earlier archive.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .exporters import PocketLogClient, serialize_csv, serialize_unmatched
from .logging_config import get_logger, safe
from .models import NormalizedTransaction
from .parsers import detect_parser
from .parsing import decode_bytes
from .rules import Rule, apply_rules

log = get_logger("pipeline")

_LOCK_NAME = ".lock"
_HEARTBEAT_NAME = ".last_run"


@dataclass
class FileResult:
    """Counts from processing a single input file."""

    parsed: int = 0
    matched: int = 0
    unmatched: int = 0
    imported: int = 0
    deduped: int = 0
    skipped: int = 0
    failed: bool = False


@dataclass
class RunSummary:
    files: int = 0
    parsed: int = 0
    matched: int = 0
    unmatched: int = 0
    imported: int = 0
    deduped: int = 0
    skipped: int = 0
    failed_files: list[str] = field(default_factory=list)

    def fold(self, result: FileResult, filename: str) -> None:
        """Fold one file's counts into the run totals."""
        self.parsed += result.parsed
        self.matched += result.matched
        self.unmatched += result.unmatched
        self.imported += result.imported
        self.deduped += result.deduped
        self.skipped += result.skipped
        if result.failed:
            self.failed_files.append(filename)


@contextmanager
def _file_lock(path: Path):
    """Best-effort cross-process lock via ``fcntl.flock`` on a lock file."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _write_unmatched(
    out_dir: Path, stem: str, ts: str, unmatched: list[NormalizedTransaction]
) -> None:
    """Write skipped bookings to a review CSV so nothing is lost silently."""
    if not unmatched:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}-{ts}.unmatched.csv"
    target.write_bytes(serialize_unmatched(unmatched))
    log.info("Wrote %d unmatched bookings to %s", len(unmatched), safe(target.name))


def _archive(src: Path, dest_dir: Path, run_ts: str) -> None:
    """Move a file into a per-run subdirectory, keeping its original name.

    Input filenames are unique within a run and ``run_ts`` is unique across
    runs, so nothing is ever overwritten and names never accumulate prefixes.
    """
    run_dir = dest_dir / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    src.replace(run_dir / src.name)


def _process_file(
    path: Path,
    config: AppConfig,
    rules: list[Rule],
    client: PocketLogClient | None,
    run_ts: str,
) -> FileResult:
    """Parse, filter, export and archive a single CSV; return its counts."""
    result = FileResult()
    raw = path.read_bytes()
    text = decode_bytes(raw)
    first_line = text.splitlines()[0] if text.strip() else ""
    parser = detect_parser(path.name, first_line, config.banks)
    if parser is None:
        log.warning("No parser matched %s — moving to failed/", safe(path.name))
        _archive(path, config.paths.failed, run_ts)
        result.failed = True
        return result

    transactions = parser.parse(text)
    matched, unmatched = apply_rules(transactions, rules, bank=parser.name)
    result.parsed = len(transactions)
    result.matched = len(matched)
    result.unmatched = len(unmatched)
    log.info(
        "%s: bank=%s parsed=%d matched=%d unmatched=%d",
        safe(path.name),
        parser.name,
        len(transactions),
        len(matched),
        len(unmatched),
    )

    ts = _timestamp()
    _write_unmatched(config.paths.output, path.stem, ts, unmatched)

    if matched:
        csv_bytes = serialize_csv(matched)
        out_target = config.paths.output / f"{parser.name}-{ts}.csv"
        config.paths.output.mkdir(parents=True, exist_ok=True)
        out_target.write_bytes(csv_bytes)
        if client is not None:
            api = client.import_csv(csv_bytes, filename=out_target.name)
            result.imported = api.imported
            result.deduped = api.deduped
            result.skipped = api.skipped
            log.info(
                "%s: imported=%d deduped=%d skipped=%d errors=%d",
                safe(path.name),
                api.imported,
                api.deduped,
                api.skipped,
                len(api.errors),
            )
            for err in api.errors[:10]:
                log.warning(
                    "%s row %s: %s %s",
                    safe(path.name),
                    err.get("row"),
                    safe(err.get("code")),
                    safe(err.get("params", "")),
                )

    _archive(path, config.paths.processed, run_ts)
    return result


def run(config: AppConfig, rules: list[Rule], *, dry_run: bool = False) -> RunSummary:
    """Process all input CSVs once. Returns a :class:`RunSummary`."""
    summary = RunSummary()
    input_dir = config.paths.input
    input_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in input_dir.glob("*.csv") if p.is_file())

    if not files:
        log.info("No input files in %s", input_dir)
        _write_heartbeat(config)
        return summary

    client: PocketLogClient | None = None
    if not dry_run:
        client = PocketLogClient(
            config.pocketlog.base_url,
            config.pocketlog.api_key or "",
            verify_tls=config.pocketlog.verify_tls,
        )
    elif dry_run:
        log.info("Dry-run: writing CSVs only, no API import")

    try:
        with _file_lock(input_dir.parent / _LOCK_NAME):
            run_ts = _timestamp()
            for path in files:
                summary.files += 1
                try:
                    result = _process_file(path, config, rules, client, run_ts)
                except Exception:  # noqa: BLE001 - isolate per-file failures
                    log.exception(
                        "Failed to process %s — moving to failed/", safe(path.name)
                    )
                    summary.failed_files.append(path.name)
                    try:
                        _archive(path, config.paths.failed, run_ts)
                    except OSError:
                        log.exception("Could not move %s to failed/", safe(path.name))
                else:
                    summary.fold(result, path.name)
    finally:
        if client is not None:
            client.close()

    log.info(
        "Run complete: files=%d parsed=%d matched=%d unmatched=%d "
        "imported=%d deduped=%d skipped=%d failed=%d",
        summary.files,
        summary.parsed,
        summary.matched,
        summary.unmatched,
        summary.imported,
        summary.deduped,
        summary.skipped,
        len(summary.failed_files),
    )
    _write_heartbeat(config)
    return summary


def heartbeat_path(config: AppConfig) -> Path:
    """Where runs record their heartbeat (consumed by ``--healthcheck``)."""
    return config.paths.input.parent / _HEARTBEAT_NAME


def _write_heartbeat(config: AppConfig) -> None:
    try:
        hb = heartbeat_path(config)
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        log.warning("Could not write heartbeat file")
