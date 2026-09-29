"""CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T10: three drifted/duplicated
constants closed, all code-derivable (no product decision needed).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.cpq.constants import NONE_DISPLAY_PLACEHOLDER
from aryx.cpq.data_table import data_table_loader, data_table_product
from aryx.cpq.data_table.data_table_resolver import (
    _clear_tables_cache,
    resolve_product_cpq_models_from_hint,
)
from aryx.cpq.engine import CpqEngine, _HINT_MIN_PHRASE_LEN, _REGION_PATTERNS
from aryx.cpq.nl_hint_extraction.question_hints import extract_hints


class _FakeRdb:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def list_ontology_types(self, workspace_id):
        return ["Astro25ConfigdataConstraint"]

    def fetch_entities_by_exact_type(self, workspace_id, ontology_type):
        return [(i, r) for i, r in enumerate(self._rows, start=1)]

    def fetch_all_entities_grouped_by_type(self, workspace_id):
        return {"Astro25ConfigdataConstraint": [(i, r) for i, r in enumerate(self._rows, start=1)]}


def _constraint_row(cpq_model: str, product_val: str) -> dict:
    return {
        "CPQModel": cpq_model, "BaseModel": "ALL",
        "attr1": "productSelectionProduct_all", "val1": product_val,
    }


def setup_function() -> None:
    _clear_tables_cache()


def test_hint_match_min_len_no_longer_drifted_from_engine(monkeypatch):
    """data_table_product.py used to hardcode its own separate
    _HINT_MATCH_MIN_LEN=4 despite its own comment claiming parity with
    engine.py's real _HINT_MIN_PHRASE_LEN=5 -- a real product string of
    exactly 4 characters (below the real 5-char threshold, above the old
    drifted 4-char one) must now correctly NOT match."""
    rows = [_constraint_row("APXAB12", "AB12")]  # exactly 4 chars
    fake = _FakeRdb(rows)
    monkeypatch.setattr(data_table_product, "get_cpq_rdb", lambda: fake)
    monkeypatch.setattr(data_table_loader, "get_cpq_rdb", lambda: fake)

    result = resolve_product_cpq_models_from_hint(
        "I want a quote for AB12 shipping", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == (), (
        "a 4-char product string must be rejected now that this module "
        "reads the real _HINT_MIN_PHRASE_LEN=5 instead of its own "
        "drifted, separately-declared 4"
    )


def test_hint_match_min_len_5_char_product_still_matches(monkeypatch):
    rows = [_constraint_row("APXABC12", "ABC12")]  # exactly 5 chars
    fake = _FakeRdb(rows)
    monkeypatch.setattr(data_table_product, "get_cpq_rdb", lambda: fake)
    monkeypatch.setattr(data_table_loader, "get_cpq_rdb", lambda: fake)

    result = resolve_product_cpq_models_from_hint(
        "I want a quote for ABC12 shipping", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == ("APXABC12",)


def test_region_patterns_now_includes_middle_east():
    assert any(value == "ME" for _pattern, value in _REGION_PATTERNS), (
        "_REGION_PATTERNS was missing ME (Middle East) entirely, unlike "
        "region_and_noise_constants.py's own real _COUNTRY_TO_REGION, "
        "which has 5 regions including ME"
    )


def test_extract_hints_recognizes_middle_east_region_mention():
    engine = MagicMock()
    engine.is_recognized_country.return_value = False
    hints = extract_hints(engine, "we need pricing for the Middle East region")
    assert hints.get("region") == "ME"


def test_none_display_placeholder_is_the_shared_constant():
    assert NONE_DISPLAY_PLACEHOLDER == "(none)"
