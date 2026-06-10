"""dadat (Bank Dadat / ``umsaetzegirokonto``) CSV parser.

Format (observed): a header row, ``;``-separated, 27 columns. Columns are
looked up by header name (resilient to re-ordering / added columns). Relevant
fields:

    Buchungsdatum (YYYY-MM-DD) · Betrag (-200,00) · Buchungstext · Umsatztext ·
    Name des Partners · Verwendungszweck

``raw_text`` for rule matching is the concatenation of the descriptive text
columns, where the merchant name typically appears (e.g. in ``Umsatztext``).
"""

from __future__ import annotations

import csv
import io

from ..models import NormalizedTransaction
from ..parsing import collapse_whitespace, parse_amount, parse_date

_DATE_FMT = "%Y-%m-%d"
_DATE_COL = "Buchungsdatum"
_AMOUNT_COL = "Betrag"
# Descriptive columns joined into the rule-matching text, in priority order.
_TEXT_COLS = ("Buchungstext", "Umsatztext", "Name des Partners", "Verwendungszweck")
# Header signature used for auto-detection.
_SIGNATURE = ("IBAN", "Buchungsdatum", "Betrag", "Buchungstext", "Umsatztext")


class DadatParser:
    name = "dadat"

    def sniff(self, first_line: str) -> bool:
        header = {h.strip() for h in first_line.rstrip("\r\n").split(";")}
        return all(col in header for col in _SIGNATURE)

    def parse(self, text: str) -> list[NormalizedTransaction]:
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        transactions: list[NormalizedTransaction] = []
        for row in reader:
            amount_raw = (row.get(_AMOUNT_COL) or "").strip()
            if not amount_raw:
                continue
            raw_text = collapse_whitespace(
                " ".join(
                    (row.get(col) or "").strip()
                    for col in _TEXT_COLS
                    if (row.get(col) or "").strip()
                )
            )
            tx = NormalizedTransaction.from_signed(
                date=parse_date(row[_DATE_COL], _DATE_FMT),
                signed_amount=parse_amount(amount_raw),
                raw_text=raw_text,
            )
            transactions.append(tx)
        return transactions
