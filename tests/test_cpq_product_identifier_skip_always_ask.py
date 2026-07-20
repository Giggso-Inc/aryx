"""Regression (Raven review, PR #104): the generic _PRODUCT_IDENTIFIER_KEYS
fragment match in is_decision_attr had no skip_always_ask carve-out, unlike
the adjacent productSelectionProduct_all-specific branch. This meant any
OTHER attr matching a product-identifier fragment (e.g. "selectModel") was
FORCED to always-ask regardless of skip_always_ask, even for a catalog whose
resolve_always_ask_skips legitimately determined the native UI never shows
it — reintroducing, for that attr, the exact "asks a question the native UI
never shows" bug PR #101/#102 fixed specifically for productSelectionProduct_all.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption

_ATTR = ConfigAttr(
    entity_id=1, variable_name="modelSelectionSelectModel_test",
    display_label="Select Model", required=False, default_value="",
    options=[
        MenuOption("VARIANT_A", "Variant A", 1),
        MenuOption("VARIANT_B", "Variant B", 2),
    ],
)


def _auto_fill(skip_always_ask):
    engine = CpqEngine()
    filled, display_filled, pending = engine.auto_fill(
        attrs=[_ATTR], hints={}, governed_ids={1}, skip_always_ask=skip_always_ask,
    )
    return filled, display_filled, pending


def test_product_identifier_fragment_always_asks_by_default():
    """No skip_always_ask entry — unconditional ask, matching every other
    catalog's behavior (existing, unchanged contract)."""
    filled, _display_filled, pending = _auto_fill(skip_always_ask=None)
    assert "modelSelectionSelectModel_test" not in filled
    assert any(a.variable_name == "modelSelectionSelectModel_test" for a in pending)


def test_product_identifier_fragment_respects_skip_always_ask_carveout():
    """A catalog that legitimately declared this attr's ask suppressed (the
    native UI never shows it) must get the blind first-by-order fallback,
    exactly like productSelectionProduct_all already does — not be forced
    to always-ask regardless."""
    filled, display_filled, pending = _auto_fill(
        skip_always_ask={"modelSelectionSelectModel_test"},
    )
    assert filled.get("modelSelectionSelectModel_test") == "VARIANT_A"
    assert display_filled.get("modelSelectionSelectModel_test") == "Variant A"
    assert not any(
        a.variable_name == "modelSelectionSelectModel_test" for a in pending
    )
