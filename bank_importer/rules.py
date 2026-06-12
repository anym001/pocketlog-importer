"""Regex rules engine — a whitelist that enriches and filters bookings.

Each rule matches a regular expression against a transaction's ``raw_text``.
The first matching rule wins (file order = priority). A booking that matches no
rule is **dropped** (no fallback): only curated, known bookings reach PocketLog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import NormalizedTransaction


@dataclass
class Rule:
    pattern: re.Pattern[str]
    description: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    type: str | None = None  # optional override of in/out
    bank: str | None = None  # restrict rule to one parser name; None = all banks


def compile_rules(raw_rules: list[dict], *, ignorecase: bool = True) -> list[Rule]:
    """Compile raw rule dicts (from YAML) into :class:`Rule` objects."""
    flags = re.IGNORECASE if ignorecase else 0
    rules: list[Rule] = []
    for index, raw in enumerate(raw_rules):
        match = raw.get("match")
        if not match:
            raise ValueError(f"rule #{index + 1} is missing a 'match' pattern")
        try:
            pattern = re.compile(match, flags)
        except re.error as exc:
            raise ValueError(f"rule #{index + 1} has an invalid regex: {exc}") from exc
        tags = raw.get("tags") or []
        if not isinstance(tags, list):
            raise ValueError(f"rule #{index + 1} 'tags' must be a list")
        rule_type = raw.get("type")
        if rule_type is not None and rule_type not in ("in", "out"):
            raise ValueError(f"rule #{index + 1} 'type' must be 'in' or 'out'")
        bank = raw.get("bank")
        if bank is not None and not isinstance(bank, str):
            raise ValueError(f"rule #{index + 1} 'bank' must be a string")
        rules.append(
            Rule(
                pattern=pattern,
                description=raw.get("description"),
                category=raw.get("category"),
                tags=[str(t) for t in tags],
                type=rule_type,
                bank=bank or None,
            )
        )
    return rules


def load_rules(path: str | Path) -> list[Rule]:
    """Load and compile rules from a YAML file (``rules:`` top-level key)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("'rules' must be a list")
    return compile_rules(raw_rules)


def apply_rules(
    transactions: list[NormalizedTransaction],
    rules: list[Rule],
    *,
    bank: str | None = None,
) -> tuple[list[NormalizedTransaction], list[NormalizedTransaction]]:
    """Split transactions into ``(matched, unmatched)``.

    Matched transactions are enriched in place from the first matching rule.
    Unmatched transactions are returned untouched and must not be imported.
    Rules with a ``bank`` field are skipped unless ``bank`` matches.
    """
    matched: list[NormalizedTransaction] = []
    unmatched: list[NormalizedTransaction] = []
    for tx in transactions:
        for rule in rules:
            if rule.bank is not None and rule.bank != bank:
                continue
            if rule.pattern.search(tx.raw_text):
                tx.description = rule.description or tx.raw_text
                if rule.category:
                    tx.category = rule.category
                if rule.tags:
                    tx.tags = list(rule.tags)
                if rule.type:
                    tx.type = rule.type
                matched.append(tx)
                break
        else:
            unmatched.append(tx)
    return matched, unmatched
