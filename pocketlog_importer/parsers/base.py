"""Parser interface shared by every bank parser."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import NormalizedTransaction


@runtime_checkable
class BankParser(Protocol):
    """A bank-specific CSV parser.

    ``name``    stable identifier used in config ``banks:`` mappings and logs.
    ``sniff``   cheap header/first-line check for auto-detection.
    ``parse``   turn the full decoded CSV text into normalised transactions.
    """

    name: str

    def sniff(self, first_line: str) -> bool: ...

    def parse(self, text: str) -> list[NormalizedTransaction]: ...
