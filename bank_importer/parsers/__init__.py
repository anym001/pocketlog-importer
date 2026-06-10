"""Parser registry and auto-detection.

A file's parser is chosen by (1) an explicit filename-glob mapping in
``config.banks`` if present, otherwise (2) sniffing each registered parser
against the file's first line.
"""

from __future__ import annotations

import fnmatch

from .base import BankParser
from .dadat import DadatParser
from .easybank import EasybankParser

# Registration order = sniff priority. dadat (header-based) is tried before
# easybank (data-shape-based) to avoid ambiguity.
_PARSERS: dict[str, BankParser] = {
    DadatParser.name: DadatParser(),
    EasybankParser.name: EasybankParser(),
}


def get_parser(name: str) -> BankParser:
    try:
        return _PARSERS[name]
    except KeyError:
        raise ValueError(f"unknown parser: {name!r}") from None


def available_parsers() -> list[str]:
    return list(_PARSERS)


def detect_parser(
    filename: str,
    first_line: str,
    mappings: list | None = None,
) -> BankParser | None:
    """Return the parser for a file, or ``None`` if none matches.

    ``mappings`` is the optional ``config.banks`` list (objects with ``match``
    glob + ``parser`` name).
    """
    for mapping in mappings or []:
        if fnmatch.fnmatch(filename, mapping.match):
            return get_parser(mapping.parser)
    for parser in _PARSERS.values():
        if parser.sniff(first_line):
            return parser
    return None


__all__ = [
    "BankParser",
    "DadatParser",
    "EasybankParser",
    "available_parsers",
    "detect_parser",
    "get_parser",
]
