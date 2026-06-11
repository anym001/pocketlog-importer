from datetime import date
from decimal import Decimal

from bank_importer.exporters import serialize_csv, serialize_unmatched
from bank_importer.models import NormalizedTransaction


def _tx(**kw) -> NormalizedTransaction:
    base = dict(
        date=date(2026, 5, 1),
        type="out",
        amount=Decimal("42.50"),
        raw_text="raw",
        description="Groceries",
        category="Food",
        tags=["a", "b"],
    )
    base.update(kw)
    return NormalizedTransaction(**base)


def test_header_and_row():
    out = serialize_csv([_tx()]).decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "date;type;amount;description;category;tags"
    assert lines[1] == "2026-05-01;out;42.50;Groceries;Food;a,b"


def test_amount_always_two_decimals():
    out = serialize_csv([_tx(amount=Decimal("9"))]).decode("utf-8")
    assert "9.00" in out.splitlines()[1]


def test_formula_injection_guard():
    out = serialize_csv([_tx(description="=SUM(A1)", category="-bad")]).decode("utf-8")
    row = out.splitlines()[1]
    assert "'=SUM(A1)" in row
    assert "'-bad" in row


def test_empty_category_serializes_blank():
    out = serialize_csv([_tx(category=None, tags=[])]).decode("utf-8")
    # date;type;amount;description;;  (empty category, empty tags)
    assert out.splitlines()[1].endswith("Groceries;;")


def test_unmatched_header_and_row():
    out = serialize_unmatched([_tx(raw_text="REWE Markt 0815")]).decode("utf-8")
    lines = out.splitlines()
    assert lines[0] == "date;type;amount;raw_text"
    assert lines[1] == "2026-05-01;out;42.50;REWE Markt 0815"


def test_unmatched_guards_raw_text_formula_injection():
    # raw_text is foreign bank text and the review CSV is opened in Excel —
    # it must get the same guard as the export columns.
    out = serialize_unmatched([_tx(raw_text="=cmd!A0")]).decode("utf-8")
    assert out.splitlines()[1].endswith("'=cmd!A0")
