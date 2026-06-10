# Contributing

This project mirrors PocketLog's branching and release model.

## Branching

```
feature/xyz ──PR──▶ dev ──(:dev image)──▶ PR ──▶ main ──▶ tag v* ──▶ release
```

- **`main`** — production-stable, protected. Updated **only** via a PR from `dev`.
- **`dev`** — integration/staging, protected. Pushing here publishes the
  `:dev` image to GHCR.
- **`feature/*`** — short-lived branches, **always** branched from `dev`.

Rules:

1. Branch from `dev`:
   ```sh
   git switch dev && git pull && git switch -c feature/xyz
   ```
2. Open the PR against **`dev`** (never directly against `main`).
3. CI (`test.yml`: ruff + pytest) must be green before merge.
4. A release is a PR `dev → main`; tagging `vX.Y.Z` builds and publishes the
   versioned image and a GitHub release.

`main` and `dev` should be protected by a ruleset (PR required, green checks,
no direct/force pushes) — a one-time GitHub setup.

## Image channels

| Tag | Meaning |
|---|---|
| `:dev` | latest `dev` push (mutable staging) |
| `:dev-<sha>` | immutable dev build |
| `:latest` | latest release |
| `:X.Y.Z` | versioned release |

## Local checks

Run before pushing — this is exactly what CI runs:

```sh
ruff check .
ruff format --check .
pytest -q
```

## Conventions

- **Everything is English** — code, comments, YAML, docs, commit messages, logs.
- Python 3.12, `ruff` for lint + format (`ruff.toml`).
- Pure parsing helpers (`bank_importer/parsing.py`) take data as arguments and
  stay unit-tested; I/O and orchestration live in `pipeline.py` / `cli.py`.
- New bank → new parser module implementing `sniff` + `parse`, registered in
  `bank_importer/parsers/__init__.py`, with a fixture-based test.
- Never log secrets (the API key); never commit a real `config.yaml` /
  `rules.yaml` or any bank data (see `.gitignore`).
