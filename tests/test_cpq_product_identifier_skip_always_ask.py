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


def _auto_fill(skip_always_ask, governed_ids=None):
    engine = CpqEngine()
    filled, display_filled, pending = engine.auto_fill(
        attrs=[_ATTR], hints={}, governed_ids=governed_ids, skip_always_ask=skip_always_ask,
    )
    return filled, display_filled, pending


def test_product_identifier_fragment_always_asks_by_default():
    """No skip_always_ask entry — unconditional ask, matching every other
    catalog's behavior (existing, unchanged contract)."""
    filled, _display_filled, pending = _auto_fill(skip_always_ask=None, governed_ids={1})
    assert "modelSelectionSelectModel_test" not in filled
    assert any(a.variable_name == "modelSelectionSelectModel_test" for a in pending)


def test_product_identifier_fragment_respects_skip_always_ask_carveout_when_governed():
    """A GOVERNED catalog that legitimately declared this attr's ask
    suppressed (the native UI never shows it) must get the blind
    first-by-order fallback, exactly like productSelectionProduct_all
    already does — not be forced to always-ask regardless. Exercises the
    is_governed-blind-fallback elif branch (is_decision_attr's own gate)."""
    filled, display_filled, pending = _auto_fill(
        skip_always_ask={"modelSelectionSelectModel_test"}, governed_ids={1},
    )
    assert filled.get("modelSelectionSelectModel_test") == "VARIANT_A"
    assert display_filled.get("modelSelectionSelectModel_test") == "Variant A"
    assert not any(
        a.variable_name == "modelSelectionSelectModel_test" for a in pending
    )


def test_product_identifier_fragment_respects_skip_always_ask_when_ungoverned():
    """Raven review follow-up (PR #104): an UNGOVERNED product-identifier
    attr never reaches the governed-blind-fallback elif at all (it requires
    is_governed=True) and falls straight to the separate pending-queue
    guard — which, before this fix, only recognised
    productSelectionProduct_all by exact name and still queued any OTHER
    product-identifier attr for a question despite skip_always_ask. Must
    not be asked."""
    filled, _display_filled, pending = _auto_fill(
        skip_always_ask={"modelSelectionSelectModel_test"}, governed_ids=None,
    )
    assert not any(
        a.variable_name == "modelSelectionSelectModel_test" for a in pending
    ), "an ungoverned product-identifier attr suppressed via skip_always_ask must not be asked"
