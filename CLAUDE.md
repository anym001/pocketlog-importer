# PocketLog Bank Importer – Claude Code Project Context

## Purpose
A small Docker container that parses bank CSV exports (easybank, dadat),
applies a regex **rules whitelist** to enrich (description/category/tags) and
**filter** bookings, and imports the result into PocketLog via its CSV API
(`POST /api/import/csv`, Bearer key with `import` scope). Companion to the
`pocketlog` repo.

## Architecture
```
/data/input/*.csv
   │  decode (utf-8-sig | cp1252)
   ▼
parsers/  (auto-detect by header/data shape)  → list[NormalizedTransaction]
   │  amount always positive, direction in `type`
   ▼
rules.py  (regex, first match wins; NO match = dropped, no fallback)
   │  → (matched, unmatched)
   ▼
exporters/pocketlog.py  → PocketLog CSV (date;type;amount;description;category;tags)
   │  matched → /data/output + POST /api/import/csv   (PocketLog dedups)
   │  unmatched → /data/output/<bank>-<ts>.unmatched.csv (review)
   ▼
original → /data/processed/ (success) | /data/failed/ (parse/import error)
```

Run model: **internal scheduler** (`scheduler.py`, cron via `croniter`) is the
container foreground process. The same run is callable on demand via
`pocketlog-import --once [--dry-run]` (used by `docker exec` / Unraid User
Scripts). A `fcntl` file lock (`/data/.lock`) serialises overlapping runs.

## Project structure
```
bank_importer/
├─ __init__.py          ← __version__ (baked from APP_VERSION at build)
├─ __main__.py / cli.py ← entry point; --once / --dry-run / --config
├─ config.py            ← pydantic AppConfig; loads config.yaml + ENV (secrets)
├─ logging_config.py    ← configure_logging(): stderr + optional rotating LOG_FILE
├─ models.py            ← NormalizedTransaction (amount>0, type in/out)
├─ parsing.py           ← PURE helpers: decode_bytes, parse_amount, parse_date,
│                         guard_csv_field (formula-injection guard)
├─ rules.py             ← regex whitelist engine; apply_rules → (matched, unmatched)
├─ pipeline.py          ← orchestration + file lock + processed/failed/heartbeat
├─ scheduler.py         ← cron loop, SIGTERM-aware
├─ parsers/             ← base.py (Protocol), __init__ (registry+detect),
│                         easybank.py, dadat.py
└─ exporters/pocketlog.py ← serialize_csv() + serialize_unmatched() + PocketLogClient
                            (httpx; retries transient failures w/ backoff)
config/                 ← *.example.yaml (real files mounted at /config, gitignored)
docker/                 ← Dockerfile, docker-entrypoint.sh (PUID/PGID+gosu), compose
tests/                  ← pytest + fixtures/ (real-bank sample CSVs)
│                         integration/ = contract tests vs. real PocketLog
.github/workflows/      ← test.yml (PR/reusable), dev.yml (:dev), build.yml
                          (release), contract.yml (nightly :latest/:dev drift)
```

## Runtime layout (container)
`/config` → `config.yaml`, `rules.yaml`, `logs/`. `/data` → `input/`,
`output/`, `processed/`, `failed/`, `.lock`, `.last_run`. Entrypoint chowns both
to PUID/PGID and drops via gosu.

## Bank formats (from real samples in tests/fixtures/)
- **easybank** (`EASYBANK_Umsatzliste_*.csv`): no header, `;`, 6 cols
  `IBAN;text;Buchungsdatum;Valutadatum;Betrag;Waehrung`; date `DD.MM.YYYY`;
  amount `-13,99` (sign = direction). `raw_text` = the free-text column (merchant
  is in there). `sniff` = data shape (IBAN + DD.MM.YYYY in row 1).
- **dadat** (`umsaetzegirokonto_*.csv`): header row, `;`, 27 cols, looked up by
  name; date `YYYY-MM-DD`; amount `-200,00`. `raw_text` = Buchungstext +
  Umsatztext + Name des Partners + Verwendungszweck. `sniff` = header signature.

## PocketLog import contract (the integration boundary)
- `POST /api/import/csv`, multipart field `file`, `Authorization: Bearer plk_…`
  (`import` scope). Columns `date;type;amount;description;category;tags` (`;`,
  UTF-8). `amount` positive; direction in `type`. Categories/tags auto-created.
  Response `{imported, skipped, deduped, errors:[{row,code,params}]}`.
- **Dedup is server-side** (hash of date|amount|description|type) → re-runs are
  idempotent; the importer keeps no own dedup state.
- **Transient failures are retried** by `PocketLogClient` (network errors, 5xx,
  429; exponential backoff, 4 attempts). 4xx is permanent — no retry. Retrying
  a whole upload is safe because of the server-side dedup.

## Conventions
- **English everywhere** (code, comments, docs, commits, logs).
- Python 3.12; `ruff` lint+format (`ruff.toml`, line 88, select E/W/F/I/UP/B).
- Pure helpers in `parsing.py` (data-in, no I/O) — unit-tested. I/O/orchestration
  in `pipeline.py`/`cli.py`.
- Secrets via ENV only (`POCKETLOG_API_KEY`), never in YAML; never logged.
- Never commit real `config.yaml`/`rules.yaml` or bank data (`.gitignore`).
- New bank: add a parser (`sniff`+`parse`), register in `parsers/__init__.py`,
  add a fixture test. Whitelist semantics: no rule match ⇒ booking dropped (no
  fallback), recorded in `*.unmatched.csv`.

## Branching / release
`feature/*` → PR → `dev` (`:dev` image) → PR → `main` → tag `vX.Y.Z`
(`:X.Y.Z` + `:latest` + GH release). PRs always against `dev`. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Local checks (= CI)
```
ruff check . && ruff format --check . && pytest -q
pytest -m integration   # contract tests; needs Docker (see below)
```

## Contract tests (the import boundary, automated)
`tests/integration/` boots a real PocketLog container (`POCKETLOG_IMAGE`,
default `ghcr.io/anym001/pocketlog:latest`), provisions admin + `import`-scope
key via the public API, and runs the real pipeline against it. Pinned: full
import round-trip (verified via `GET /api/export/csv`), dedup idempotency,
the per-row error format `{row, code, params}` (only codes the importer logs),
and scope/auth semantics (403/401). Excluded from the default `pytest -q` via
marker `integration`. CI: PR gate against `:latest` (test.yml `contract` job);
nightly drift run against `:latest` + `:dev` (contract.yml, runs from the
default branch). A red nightly `:dev` = PocketLog is about to break the
contract — fix it there before releasing.

## Verification (manual end-to-end)
Start a local PocketLog, create an `import`-scope API key, set
`POCKETLOG_API_KEY`, point `pocketlog.base_url` at it, drop a bank CSV into
`/data/input`, run `pocketlog-import --once`. Check PocketLog
(`GET /api/transactions` / `GET /api/export/csv`). A second run of the same file
yields `deduped > 0`, `imported = 0` (idempotency).
