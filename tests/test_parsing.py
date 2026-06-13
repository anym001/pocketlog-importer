from datetime import date
from decimal import Decimal

import pytest

from pocketlog_importer.parsing import (
    collapse_whitespace,
    decode_bytes,
    guard_csv_field,
    parse_amount,
    parse_date,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("-13,99", Decimal("-13.99")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("39,00", Decimal("39.00")),
        ("  -200,00 ", Decimal("-200.00")),
        ("€ 9,90", Decimal("9.90")),
        ("1234", Decimal("1234")),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "abc", "--"])
def test_parse_amount_invalid(bad):
    with pytest.raises(ValueError):
        parse_amount(bad)


def test_parse_date_formats():
    assert parse_date("08.06.2026", "%d.%m.%Y") == date(2026, 6, 8)
    assert parse_date("2026-05-15", "%Y-%m-%d") == date(2026, 5, 15)


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        parse_date("99.99.9999", "%d.%m.%Y")


def test_decode_bytes_utf8_and_cp1252():
    assert decode_bytes("Würth".encode()) == "Würth"
    assert decode_bytes("Würth".encode("cp1252")) == "Würth"


def test_collapse_whitespace():
    assert collapse_whitespace("a   b\t c\n") == "a b c"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=SUM(A1)", "'=SUM(A1)"),
        ("+43 660 123", "'+43 660 123"),
        ("-minus", "'-minus"),
        ("@cmd", "'@cmd"),
        ("safe text", "safe text"),
        ("", ""),
    ],
)
def test_guard_csv_field(raw, expected):
    assert guard_csv_field(raw) == expected
