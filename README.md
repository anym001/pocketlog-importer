# PocketLog Bank Importer

A small Docker container that turns bank CSV exports (**easybank**, **dadat**)
into [PocketLog](https://github.com/anym001/pocketlog) transactions. You drop a
CSV into a folder, a rules whitelist decides what gets imported (description,
category, tags), and the result is pushed to PocketLog via its CSV import API.

## How it works

```
bank export ─▶ /data/input ─▶ parse ─▶ rules.yaml (whitelist) ─▶ /data/output ─▶ PocketLog API
                                            │
                                            └─ no match ─▶ <bank>.unmatched.csv (review)
```

1. The container runs an **internal scheduler** (cron, default hourly).
2. Each `*.csv` in `/data/input` is auto-detected (easybank / dadat), parsed and
   normalised (amount always positive, direction in `type`).
3. Every booking is matched against `rules.yaml` (regex, case-insensitive,
   first match wins). **A booking that matches no rule is dropped** — only
   curated bookings reach PocketLog. Dropped bookings are written to a
   `*.unmatched.csv` for review so you can add a rule later.
4. Matched bookings are written to `/data/output/<bank>-<ts>.csv` and imported
   via `POST /api/import/csv`. PocketLog deduplicates, so re-runs are safe.
   Transient API failures (network errors, 5xx, 429) are retried with
   exponential backoff before a file counts as failed.
5. The processed original is moved to `/data/processed/`. Files that fail to
   parse or import go to `/data/failed/`.

## Quick start

1. **Create an API key** in PocketLog (UI → API keys) with the **`import`** scope.
2. Copy the example config and rules:
   ```sh
   mkdir -p config data/input
   cp config/config.example.yaml config/config.yaml
   cp config/rules.example.yaml  config/rules.yaml
   ```
   Edit `config/config.yaml` → set `pocketlog.base_url`. Edit `config/rules.yaml`
   to match your bookings.
3. Start the container (see `docker/docker-compose.example.yml`):
   ```sh
   POCKETLOG_API_KEY=plk_xxx docker compose -f docker/docker-compose.example.yml up -d
   ```
4. Drop a bank CSV into `data/input/`. The scheduler picks it up; or trigger it
   immediately:
   ```sh
   docker exec pocketlog-bank-importer pocketlog-import --once
   ```

### Try it safely first (dry-run)

`--dry-run` writes the output CSVs but does **not** import anything:

```sh
docker exec pocketlog-bank-importer pocketlog-import --once --dry-run
```

## Triggering

Three equivalent ways to run the pipeline:

| Method | Command |
|---|---|
| Automatic | internal scheduler (`schedule.cron` in `config.yaml`) |
| On demand | `docker exec pocketlog-bank-importer pocketlog-import --once` |
| Test | `... pocketlog-import --once --dry-run` |

The `--once` path is ideal for **Unraid User Scripts**. A file lock prevents a
manual run from overlapping with a scheduler tick.

## Configuration

`config/config.yaml` — see [`config/config.example.yaml`](config/config.example.yaml).
The PocketLog **API key is never stored in YAML**; provide it via the
`POCKETLOG_API_KEY` environment variable.

### Rules

`config/rules.yaml` — see [`config/rules.example.yaml`](config/rules.example.yaml).

```yaml
rules:
  - match: "STREAMINGCO"            # regex, case-insensitive, tested against booking text
    description: "Streaming Service" # overrides description (default: raw booking text)
    category: "Entertainment"        # PocketLog category (auto-created if new)
    tags: [subscription]             # tags (auto-created if new)
    # type: in                       # optional, overrides the amount-sign direction
    # bank: easybank                 # optional, restrict to one parser
```

Rules are evaluated top to bottom; the **first** matching rule wins.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `POCKETLOG_API_KEY` | — | **Required** for real imports (`import` scope key) |
| `POCKETLOG_BASE_URL` | — | Optional override of `pocketlog.base_url` |
| `PUID` / `PGID` | `1000` | Ownership of `/config` + `/data` (Unraid: `99` / `100`) |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `LOG_FILE` | — | Optional rotating log file, e.g. `/config/logs/importer.log` |
| `LOG_FILE_MAX_BYTES` | `1048576` | Rotation size |
| `LOG_FILE_BACKUPS` | `5` | Rotated copies kept |

## Volumes

| Path | Contents |
|---|---|
| `/config` | `config.yaml`, `rules.yaml`, optional `logs/` |
| `/data/input` | drop bank CSVs here |
| `/data/output` | generated PocketLog CSVs + `*.unmatched.csv` |
| `/data/processed` | successfully processed originals, one subdirectory per run |
| `/data/failed` | files that failed to parse or import, one subdirectory per run |

## Supported banks

| Bank | File | Format |
|---|---|---|
| easybank | `EASYBANK_Umsatzliste_*.csv` | no header, 6 cols, `DD.MM.YYYY`, `-13,99` |
| dadat | `umsaetzegirokonto_*.csv` | header, 27 cols, `YYYY-MM-DD`, `-200,00` |

Adding a bank = a new parser in `bank_importer/parsers/` (implement `sniff` +
`parse`) registered in `parsers/__init__.py`.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .
ruff check . && ruff format --check . && pytest -q
```

### Contract tests

`tests/integration/` runs the real pipeline against a real PocketLog container
and pins the import API contract (round-trip, dedup idempotency, per-row error
format, auth scopes). Requires Docker; excluded from the default `pytest -q`
run:

```sh
pytest -m integration                                          # released image
POCKETLOG_IMAGE=ghcr.io/anym001/pocketlog:dev pytest -m integration
```

CI runs them on every PR against the released image, and nightly against
`:latest` + `:dev` (`contract.yml`) to catch contract drift from the PocketLog
side before it is released.

Branching and release flow: see [`CONTRIBUTING.md`](CONTRIBUTING.md).
