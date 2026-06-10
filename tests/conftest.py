"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def easybank_csv() -> bytes:
    return (FIXTURES / "easybank_sample.csv").read_bytes()


@pytest.fixture
def dadat_csv() -> bytes:
    return (FIXTURES / "dadat_sample.csv").read_bytes()
