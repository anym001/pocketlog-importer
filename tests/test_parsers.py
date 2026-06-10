from datetime import date
from decimal import Decimal

from bank_importer.parsers import detect_parser, get_parser
from bank_importer.parsing import decode_bytes


def test_easybank_parse(easybank_csv):
    parser = get_parser("easybank")
    txs = parser.parse(decode_bytes(easybank_csv))
    assert len(txs) == 5
    first = txs[0]
    assert first.date == date(2026, 6, 8)
    assert first.type == "out"
    assert first.amount == Decimal("13.99")
    assert "MUSIKBEISPIEL" in first.raw_text
    # whitespace runs collapsed
    assert "  " not in first.raw_text


def test_dadat_parse(dadat_csv):
    parser = get_parser("dadat")
    txs = parser.parse(decode_bytes(dadat_csv))
    assert len(txs) == 3
    # Row 3 is the Shopbeispiel e-commerce booking.
    shopbeispiel = txs[2]
    assert shopbeispiel.date == date(2026, 5, 11)
    assert shopbeispiel.type == "out"
    assert shopbeispiel.amount == Decimal("35.98")
    assert "SHOPBEISPIEL" in shopbeispiel.raw_text.upper()


def test_autodetect_easybank(easybank_csv):
    text = decode_bytes(easybank_csv)
    parser = detect_parser("EASYBANK_Umsatzliste.csv", text.splitlines()[0], [])
    assert parser is not None and parser.name == "easybank"


def test_autodetect_dadat(dadat_csv):
    text = decode_bytes(dadat_csv)
    parser = detect_parser("umsaetzegirokonto.csv", text.splitlines()[0], [])
    assert parser is not None and parser.name == "dadat"


def test_autodetect_unknown():
    assert detect_parser("mystery.csv", "foo,bar,baz", []) is None
