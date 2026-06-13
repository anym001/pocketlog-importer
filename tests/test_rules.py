from datetime import date
from decimal import Decimal

from pocketlog_importer.models import NormalizedTransaction
from pocketlog_importer.rules import apply_rules, compile_rules


def _tx(raw_text: str) -> NormalizedTransaction:
    return NormalizedTransaction(
        date=date(2026, 1, 1), type="out", amount=Decimal("1.00"), raw_text=raw_text
    )


def test_match_enriches():
    rules = compile_rules(
        [
            {
                "match": "STREAMINGCO",
                "description": "Streaming Service",
                "category": "Entertainment",
                "tags": ["subscription"],
            }
        ]
    )
    matched, unmatched = apply_rules([_tx("... STREAMINGCO ...")], rules)
    assert not unmatched
    assert matched[0].description == "Streaming Service"
    assert matched[0].category == "Entertainment"
    assert matched[0].tags == ["subscription"]


def test_no_match_is_dropped():
    rules = compile_rules([{"match": "VIDEOSERVICE", "category": "Entertainment"}])
    matched, unmatched = apply_rules([_tx("random merchant")], rules)
    assert not matched
    assert len(unmatched) == 1


def test_first_rule_wins():
    rules = compile_rules(
        [
            {"match": "RENTINGCO", "category": "Housing"},
            {"match": "RENTINGCO", "category": "Other"},
        ]
    )
    matched, _ = apply_rules([_tx("RENTINGCO VS 06")], rules)
    assert matched[0].category == "Housing"


def test_case_insensitive_regex():
    rules = compile_rules([{"match": "onlineshop", "category": "Clothing"}])
    matched, _ = apply_rules([_tx("ONLINESHOP PAYMENTS")], rules)
    assert matched[0].category == "Clothing"


def test_description_defaults_to_raw_text():
    rules = compile_rules([{"match": "ELECTRICITYCO", "category": "Housing"}])
    matched, _ = apply_rules([_tx("Electricityco Ltd")], rules)
    assert matched[0].description == "Electricityco Ltd"


def test_type_override():
    rules = compile_rules([{"match": "REFUND", "category": "X", "type": "in"}])
    tx = _tx("REFUND")
    matched, _ = apply_rules([tx], rules)
    assert matched[0].type == "in"


def test_invalid_regex_raises():
    import pytest

    with pytest.raises(ValueError):
        compile_rules([{"match": "([unclosed"}])


def test_bank_filter_matches_correct_bank():
    rules = compile_rules([{"match": "MERCHANT", "category": "X", "bank": "easybank"}])
    matched, unmatched = apply_rules([_tx("MERCHANT")], rules, bank="easybank")
    assert len(matched) == 1
    assert not unmatched


def test_bank_filter_skips_other_bank():
    rules = compile_rules([{"match": "MERCHANT", "category": "X", "bank": "easybank"}])
    matched, unmatched = apply_rules([_tx("MERCHANT")], rules, bank="dadat")
    assert not matched
    assert len(unmatched) == 1


def test_rule_without_bank_applies_to_all_banks():
    rules = compile_rules([{"match": "MERCHANT", "category": "X"}])
    for bank in ("easybank", "dadat", None):
        matched, _ = apply_rules([_tx("MERCHANT")], rules, bank=bank)
        assert len(matched) == 1
