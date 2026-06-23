from datetime import date
from decimal import Decimal

from pocketlog_importer.parsers import detect_parser, get_parser
from pocketlog_importer.parsing import decode_bytes


def test_easybank_parse(easybank_csv):
    parser = get_parser("easybank")
    txs = parser.parse(decode_bytes(easybank_csv))
    assert len(txs) == 5
    first = txs[0]
    assert first.date == date(2026, 6, 8)
    assert first.type == "out"
    assert first.amount == Decimal("13.99")
    assert "STREAMINGCO" in first.raw_text
    # whitespace runs collapsed
    assert "  " not in first.raw_text


def test_dadat_parse(dadat_csv):
    parser = get_parser("dadat")
    txs = parser.parse(decode_bytes(dadat_csv))
    assert len(txs) == 3
    # Row 3 is the online shop e-commerce booking.
    online_shop = txs[2]
    assert online_shop.date == date(2026, 5, 11)
    assert online_shop.type == "out"
    assert online_shop.amount == Decimal("35.98")
    assert "ONLINESHOP" in online_shop.raw_text.upper()


def test_autodetect_easybank(easybank_csv):
    text = decode_bytes(easybank_csv)
    parser = detect_parser("EASYBANK_Umsatzliste.csv", text.splitlines()[0], [])
    assert parser is not None and parser.name == "easybank"


def test_autodetect_dadat(dadat_csv):
    text = decode_bytes(dadat_csv)
    parser = detect_parser("umsaetzegirokonto.csv", text.splitlines()[0], [])
    assert parser is not None and parser.name == "dadat"


def test_easybank_skips_zero_amount():
    # A zero-amount row (e.g. an info/balance line) carries no direction and
    # must be skipped rather than crash the whole file.
    text = (
        "AT270000000000000001;Real booking;08.06.2026;08.06.2026;-13,99;EUR\r\n"
        "AT270000000000000001;Info line;08.06.2026;08.06.2026;0,00;EUR\r\n"
    )
    txs = get_parser("easybank").parse(text)
    assert len(txs) == 1
    assert txs[0].amount == Decimal("13.99")


def test_dadat_skips_zero_amount():
    header = "IBAN;Buchungsdatum;Betrag;Buchungstext;Umsatztext"
    text = (
        f"{header}\r\n"
        "AT27;2026-05-11;-35,98;Card;ONLINESHOP\r\n"
        "AT27;2026-05-11;0,00;Info;BALANCE\r\n"
    )
    txs = get_parser("dadat").parse(text)
    assert len(txs) == 1
    assert txs[0].amount == Decimal("35.98")


def test_autodetect_unknown():
    assert detect_parser("mystery.csv", "foo,bar,baz", []) is None
