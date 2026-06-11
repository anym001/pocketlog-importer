"""Pipeline orchestration: discover -> parse -> rules -> export -> archive.

A single ``run()`` processes every CSV in the input directory. It is guarded by
a file lock so a manual ``docker exec ... --once`` run never overlaps with a
scheduler tick. Re-runs are safe because PocketLog deduplicates imports and the
move into ``processed/`` is atomic.
"""

from __future__ import annotations

import csv
import io
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .exporters import PocketLogClient, serialize_csv
from .logging_config import get_logger, safe
from .models import NormalizedTransaction
from .parsers import detect_parser
from .parsing import decode_bytes
from .rules import Rule, apply_rules

log = get_logger("pipeline")

_LOCK_NAME = ".lock"
_HEARTBEAT_NAME = ".last_run"


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
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_unmatched(
    out_dir: Path, stem: str, ts: str, unmatched: list[NormalizedTransaction]
) -> None:
    """Write skipped bookings to a review CSV so nothing is lost silently."""
    if not unmatched:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}-{ts}.unmatched.csv"
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["date", "type", "amount", "raw_text"])
    for tx in unmatched:
        writer.writerow([tx.date.isoformat(), tx.type, f"{tx.amount:.2f}", tx.raw_text])
    target.write_bytes(buffer.getvalue().encode("utf-8"))
    log.info("Wrote %d unmatched bookings to %s", len(unmatched), safe(target.name))


def _move(src: Path, dest_dir: Path, ts: str) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    src.replace(dest_dir / f"{ts}-{src.name}")


def _process_file(
    path: Path,
    config: AppConfig,
    rules: list[Rule],
    client: PocketLogClient | None,
    summary: RunSummary,
) -> None:
    raw = path.read_bytes()
    text = decode_bytes(raw)
    first_line = text.splitlines()[0] if text.strip() else ""
    parser = detect_parser(path.name, first_line, config.banks)
    if parser is None:
        log.warning("No parser matched %s — moving to failed/", safe(path.name))
        summary.failed_files.append(path.name)
        _move(path, config.paths.failed, _timestamp())
        return

    transactions = parser.parse(text)
    matched, unmatched = apply_rules(transactions, rules)
    summary.parsed += len(transactions)
    summary.matched += len(matched)
    summary.unmatched += len(unmatched)
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
            result = client.import_csv(csv_bytes, filename=out_target.name)
            summary.imported += result.imported
            summary.deduped += result.deduped
            summary.skipped += result.skipped
            log.info(
                "%s: imported=%d deduped=%d skipped=%d errors=%d",
                safe(path.name),
                result.imported,
                result.deduped,
                result.skipped,
                len(result.errors),
            )
            for err in result.errors[:10]:
                log.warning(
                    "%s row %s: %s %s",
                    safe(path.name),
                    err.get("row"),
                    safe(err.get("code")),
                    safe(err.get("params", "")),
                )

    _move(path, config.paths.processed, ts)


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
            for path in files:
                summary.files += 1
                try:
                    _process_file(path, config, rules, client, summary)
                except Exception:  # noqa: BLE001 - isolate per-file failures
                    log.exception(
                        "Failed to process %s — moving to failed/", safe(path.name)
                    )
                    summary.failed_files.append(path.name)
                    try:
                        _move(path, config.paths.failed, _timestamp())
                    except OSError:
                        log.exception("Could not move %s to failed/", safe(path.name))
    finally:
        if client is not None:
            client.close()

    log.info(
        "Run complete: files=%d parsed=%d matched=%d unmatched=%d "
        "imported=%d deduped=%d failed=%d",
        summary.files,
        summary.parsed,
        summary.matched,
        summary.unmatched,
        summary.imported,
        summary.deduped,
        len(summary.failed_files),
    )
    _write_heartbeat(config)
    return summary


def _write_heartbeat(config: AppConfig) -> None:
    try:
        hb = config.paths.input.parent / _HEARTBEAT_NAME
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        log.warning("Could not write heartbeat file")
