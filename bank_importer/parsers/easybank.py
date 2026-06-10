"""easybank ``Umsatzliste`` CSV parser.

Format (observed): no header row, ``;``-separated, 6 columns:

    IBAN ; booking text ; Buchungsdatum ; Valutadatum ; Betrag ; currency

Example row::

    AT27...;Bezahlung Karte ... MUSIKBEISPIEL ...;08.06.2026;08.06.2026;-13,99;EUR

Dates are ``DD.MM.YYYY``; the amount is German-formatted (``-13,99``) with the
sign carrying the direction. The merchant lives inside the free-text column,
which becomes ``raw_text`` for rule matching.
"""

from __future__ import annotations

import csv
import io
import re

from ..models import NormalizedTransaction
from ..parsing import collapse_whitespace, parse_amount, parse_date

_DATE_FMT = "%d.%m.%Y"
_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")
_DE_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

# Column indices within a row.
_COL_TEXT = 1
_COL_DATE = 2
_COL_AMOUNT = 4
_EXPECTED_COLS = 6


class EasybankParser:
    name = "easybank"

    def sniff(self, first_line: str) -> bool:
        """easybank has no header: detect by the data shape of the first row."""
        fields = first_line.rstrip("\r\n").split(";")
        if len(fields) != _EXPECTED_COLS:
            return False
        return bool(
            _IBAN_RE.match(fields[0].strip())
            and _DE_DATE_RE.match(fields[_COL_DATE].strip())
        )

    def parse(self, text: str) -> list[NormalizedTransaction]:
        reader = csv.reader(io.StringIO(text), delimiter=";")
        transactions: list[NormalizedTransaction] = []
        for fields in reader:
            if len(fields) < _EXPECTED_COLS or not fields[0].strip():
                continue  # skip blank/short lines defensively
            signed = parse_amount(fields[_COL_AMOUNT])
            tx = NormalizedTransaction.from_signed(
                date=parse_date(fields[_COL_DATE], _DATE_FMT),
                signed_amount=signed,
                raw_text=collapse_whitespace(fields[_COL_TEXT]),
            )
            transactions.append(tx)
        return transactions
