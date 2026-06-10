"""Shared parsing helpers for bank CSV exports.

Pure functions only (no I/O, no app state) so they are easy to unit-test and
reusable across the per-bank parsers.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# Bank exports are usually UTF-8 (optionally with BOM) or Windows CP1252
# (Excel default in the German-speaking world). Try UTF-8 first, fall back.
_ENCODINGS = ("utf-8-sig", "cp1252")

_WHITESPACE = re.compile(r"\s+")


def decode_bytes(raw: bytes) -> str:
    """Decode raw CSV bytes, tolerating UTF-8(-BOM) and CP1252."""
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # Last resort: never crash on a single bad byte.
    return raw.decode("utf-8", errors="replace")


def collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces and trim."""
    return _WHITESPACE.sub(" ", text).strip()


def parse_amount(raw: str) -> Decimal:
    """Parse a German/US formatted money string into a signed ``Decimal``.

    Handles ``-13,99``, ``1.234,56`` (European) and ``1,234.56`` (US). The last
    of ``,``/``.`` present is treated as the decimal separator. Strips ``€`` and
    whitespace. Raises ``ValueError`` on an empty or unparseable value.
    """
    s = raw.strip().replace("€", "").replace(" ", "").replace("\xa0", "")
    if not s:
        raise ValueError("empty amount")
    negative = s.startswith("-")
    s = s.lstrip("+-")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # European: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:  # US: 1,234.56
            s = s.replace(",", "")
    elif "," in s:  # 13,99 -> 13.99
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"unrecognised amount: {raw!r}") from exc
    return -value if negative else value


def parse_date(raw: str, fmt: str) -> date:
    """Parse a date string with an explicit ``strptime`` format."""
    try:
        return datetime.strptime(raw.strip(), fmt).date()
    except ValueError as exc:
        raise ValueError(f"unrecognised date: {raw!r}") from exc
