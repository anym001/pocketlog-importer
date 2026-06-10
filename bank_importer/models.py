"""Core domain model shared between parsers, rules and the exporter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class NormalizedTransaction:
    """A single booking, normalised away from any bank-specific format.

    ``amount`` is always positive; the direction lives solely in ``type``
    (mirrors PocketLog's import contract). ``raw_text`` is the concatenated
    bank booking text used for rule matching; ``description``/``category``/
    ``tags`` are filled in by the rules engine before export.
    """

    date: date
    type: str  # "in" | "out"
    amount: Decimal  # always positive
    raw_text: str
    description: str = ""
    category: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_signed(
        cls, *, date: date, signed_amount: Decimal, raw_text: str
    ) -> NormalizedTransaction:
        """Build a transaction, deriving ``type`` from the amount's sign.

        Raises ``ValueError`` on a zero amount (no direction can be inferred,
        and PocketLog would reject it anyway).
        """
        if signed_amount == 0:
            raise ValueError("zero amount has no direction")
        return cls(
            date=date,
            type="out" if signed_amount < 0 else "in",
            amount=abs(signed_amount),
            raw_text=raw_text,
        )
