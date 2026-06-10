from datetime import date
from decimal import Decimal

from bank_importer.models import NormalizedTransaction
from bank_importer.rules import apply_rules, compile_rules


def _tx(raw_text: str) -> NormalizedTransaction:
    return NormalizedTransaction(
        date=date(2026, 1, 1), type="out", amount=Decimal("1.00"), raw_text=raw_text
    )


def test_match_enriches():
    rules = compile_rules(
        [
            {
                "match": "MUSIKBEISPIEL",
                "description": "Musikbeispiel",
                "category": "Freizeit",
                "tags": ["abo"],
            }
        ]
    )
    matched, unmatched = apply_rules([_tx("... MUSIKBEISPIEL ...")], rules)
    assert not unmatched
    assert matched[0].description == "Musikbeispiel"
    assert matched[0].category == "Freizeit"
    assert matched[0].tags == ["abo"]


def test_no_match_is_dropped():
    rules = compile_rules([{"match": "VIDEOBEISPIEL", "category": "Freizeit"}])
    matched, unmatched = apply_rules([_tx("random merchant")], rules)
    assert not matched
    assert len(unmatched) == 1


def test_first_rule_wins():
    rules = compile_rules(
        [
            {"match": "MIETBEISPIEL", "category": "Wohnen"},
            {"match": "MIETBEISPIEL", "category": "Andere"},
        ]
    )
    matched, _ = apply_rules([_tx("MIETBEISPIEL VS 06")], rules)
    assert matched[0].category == "Wohnen"


def test_case_insensitive_regex():
    rules = compile_rules([{"match": "shopbeispiel", "category": "Kleidung"}])
    matched, _ = apply_rules([_tx("SHOPBEISPIEL PAYMENTS")], rules)
    assert matched[0].category == "Kleidung"


def test_description_defaults_to_raw_text():
    rules = compile_rules([{"match": "STROMBEISPIEL", "category": "Wohnen"}])
    matched, _ = apply_rules([_tx("Strombeispiel GmbH")], rules)
    assert matched[0].description == "Strombeispiel GmbH"


def test_type_override():
    rules = compile_rules([{"match": "REFUND", "category": "X", "type": "in"}])
    tx = _tx("REFUND")
    matched, _ = apply_rules([tx], rules)
    assert matched[0].type == "in"


def test_invalid_regex_raises():
    import pytest

    with pytest.raises(ValueError):
        compile_rules([{"match": "([unclosed"}])
