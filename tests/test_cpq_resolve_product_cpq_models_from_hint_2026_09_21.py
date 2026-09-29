"""Tests for data_table_resolver.resolve_product_cpq_models_from_hint --
docs/Hardware_Version_APX3000_Product_Anchoring_Issue.md v2.2's merged
recommendation, step 1: resolve a real CPQModel from the customer's own
raw wording (e.g. "I want APX 3000 for United States"), not an already-
exact product name, breaking the chicken-and-egg gap where the device
name is only known from what the customer originally typed.

resolve_product_cpq_models_from_hint routes through _load_all_tables(),
which calls get_cpq_rdb() bound in data_table_loader's own module
namespace, not data_table_product's -- patching only data_table_product.
get_cpq_rdb silently would not intercept it (same lesson as
test_data_table_feature_region_search_2026_09_16.py's own _patch_rdb,
which patches both modules for the identical reason).
"""
from __future__ import annotations

from aryx.cpq.data_table import data_table_loader, data_table_product
from aryx.cpq.data_table.data_table_resolver import (
    _clear_tables_cache,
    resolve_product_cpq_models_from_hint,
)


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


def _patch_rdb(monkeypatch, rows: list[dict]) -> None:
    fake = _FakeRdb(rows)
    monkeypatch.setattr(data_table_product, "get_cpq_rdb", lambda: fake)
    monkeypatch.setattr(data_table_loader, "get_cpq_rdb", lambda: fake)


def setup_function() -> None:
    _clear_tables_cache()


def test_resolves_a_single_confident_substring_match(monkeypatch):
    rows = [
        _constraint_row("APX3000", "APX 3000"),
        _constraint_row("APXNEXTENHANCED", "APX NEXT ENHANCED"),
    ]
    _patch_rdb(monkeypatch, rows)

    result = resolve_product_cpq_models_from_hint(
        "I want APX 3000 for United States", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == ("APX3000",)


def test_returns_empty_when_no_real_product_matches(monkeypatch):
    rows = [_constraint_row("APXNEXTENHANCED", "APX NEXT ENHANCED")]
    _patch_rdb(monkeypatch, rows)

    result = resolve_product_cpq_models_from_hint(
        "I want APX 3000 for United States", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == (), "no real ingested product string matches -- never guess"


def test_returns_empty_when_two_real_products_both_match(monkeypatch):
    """Genuine ambiguity -- e.g. a long sentence that happens to contain
    two distinct real catalog product strings -- must never guess."""
    rows = [
        _constraint_row("APX3000", "APX 3000"),
        _constraint_row("APX6500", "APX 6500"),
    ]
    _patch_rdb(monkeypatch, rows)

    result = resolve_product_cpq_models_from_hint(
        "compare APX 3000 against APX 6500 for United States",
        workspace_id=97, catalog_prefix="Astro25Configdata",
    )
    assert result == ()


def test_returns_empty_for_unresolvable_free_text(monkeypatch):
    rows = [_constraint_row("APX3000", "APX 3000")]
    _patch_rdb(monkeypatch, rows)

    result = resolve_product_cpq_models_from_hint(
        "I need a quote for some radios", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == ()


def test_guards_against_a_very_short_coincidental_match(monkeypatch):
    """A real product string shorter than _HINT_MATCH_MIN_LEN must not be
    trusted as a deliberate mention -- too easy to match by coincidence."""
    rows = [_constraint_row("APXAB", "AB")]
    _patch_rdb(monkeypatch, rows)

    result = resolve_product_cpq_models_from_hint(
        "I want a quote for AB shipping", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == ()


def test_multiple_cpq_models_for_the_same_matched_product(monkeypatch):
    rows = [
        _constraint_row("APX3000", "APX 3000"),
        _constraint_row("APX3000_BOM", "APX 3000"),
    ]
    _patch_rdb(monkeypatch, rows)

    result = resolve_product_cpq_models_from_hint(
        "I want APX 3000 for United States", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    )
    assert result == ("APX3000", "APX3000_BOM")
