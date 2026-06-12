"""Fixtures for the PocketLog contract tests.

These tests pin the integration boundary documented in CLAUDE.md ("PocketLog
import contract") against a real PocketLog instance: a throwaway container is
started from ``POCKETLOG_IMAGE`` (default the released image), the first admin
and an ``import``-scoped API key are provisioned through the public API — the
same flow an operator follows — and the real pipeline runs against it.

The tests are excluded from the default unit run (see ``addopts`` in
pytest.ini); select them with ``pytest -m integration``. Every test module in
this directory must set ``pytestmark = pytest.mark.integration``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator

import httpx
import pytest

DEFAULT_IMAGE = "ghcr.io/anym001/pocketlog:latest"
_HEALTH_TIMEOUT = 90.0

ADMIN_USERNAME = "contract-admin"
# Must satisfy PocketLog's password policy (>= 12 chars, four character
# classes). Throwaway container, so a literal here is fine.
ADMIN_PASSWORD = "Contract-Admin-2026!"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True
    )


def _wait_for_health(base_url: str, container_id: str, image: str) -> None:
    deadline = time.monotonic() + _HEALTH_TIMEOUT
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            if httpx.get(base_url + "/api/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    logs = _docker("logs", container_id, check=False)
    pytest.fail(
        f"{image} did not become healthy within {_HEALTH_TIMEOUT:.0f}s "
        f"({last_error})\n{logs.stdout}{logs.stderr}"
    )


@pytest.fixture(scope="session")
def pocketlog_base_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """Start a throwaway PocketLog container and yield its base URL."""
    if shutil.which("docker") is None or _docker("info", check=False).returncode != 0:
        pytest.skip("docker is not available")

    image = os.environ.get("POCKETLOG_IMAGE", DEFAULT_IMAGE)
    try:
        proc = _docker(
            "run",
            "-d",
            # The tests talk plain HTTP to localhost; without this the
            # session/CSRF cookies carry `Secure` and the client drops them.
            "-e",
            "SESSION_COOKIE_SECURE=0",
            "-p",
            "127.0.0.1:0:8000",
            image,
        )
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"could not start {image}: {exc.stderr.strip()}")
    container_id = proc.stdout.strip()

    try:
        host_port = _docker("port", container_id, "8000").stdout.strip().splitlines()[0]
        base_url = f"http://{host_port}"
        _wait_for_health(base_url, container_id, image)
        yield base_url
    finally:
        if request.session.testsfailed:
            logs = _docker("logs", container_id, check=False)
            sys.stderr.write(f"\n--- {image} logs ---\n{logs.stdout}{logs.stderr}\n")
        _docker("rm", "-f", container_id, check=False)


@pytest.fixture(scope="session")
def admin_session(pocketlog_base_url: str) -> Iterator[httpx.Client]:
    """Session-cookie client for the first admin; provisions the account."""
    client = httpx.Client(base_url=pocketlog_base_url, timeout=30.0)

    status = client.get("/api/auth/setup-status")
    assert status.status_code == 200, status.text
    assert status.json()["needs_setup"] is True

    setup = client.post(
        "/api/auth/setup",
        json={
            "username": ADMIN_USERNAME,
            "password": ADMIN_PASSWORD,
            "locale": "en-GB",
        },
    )
    assert setup.status_code == 200, setup.text

    login = client.post(
        "/api/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text

    yield client
    client.close()


@pytest.fixture(scope="session")
def make_api_key(admin_session: httpx.Client) -> Callable[[str, list[str]], str]:
    """Factory creating bearer keys via the session API (cookie + CSRF)."""

    def _make(name: str, scopes: list[str]) -> str:
        csrf = admin_session.cookies.get("pocketlog_csrf")
        assert csrf, "login must have set the CSRF cookie"
        resp = admin_session.post(
            "/api/api-keys",
            json={"name": name, "scopes": scopes},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201, resp.text
        key = resp.json()["key"]
        assert key.startswith("plk_")
        return key

    return _make


@pytest.fixture(scope="session")
def import_api_key(make_api_key: Callable[[str, list[str]], str]) -> str:
    """The key the real importer uses: ``import`` scope only."""
    return make_api_key("contract-importer", ["import"])
