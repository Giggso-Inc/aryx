"""selectmodel always-ask override respects skip_always_ask.

Raven review finding (M2): tests/test_cpq_product_identifier_skip_always_ask.py
was deleted outright when the broad _PRODUCT_IDENTIFIER_KEYS generalization
was narrowed down to just "selectmodel" (see engine.py's is_decision_attr —
"basemodel"/"modelname"/etc. no longer force always-ask, only "selectmodel"
does, per the live SVX Select Model finding). No replacement test proved the
narrowed override still respects skip_always_ask the same way
productSelectionProduct_all's own branch does. Currently dormant —
resolve_always_ask_skips only ever populates productSelectionProduct_all
today — but without this carve-out, any future extension of that method to
a "selectmodel"-named attr would force an always-ask regardless, silently
reintroducing the exact "asks a question the native UI never shows" bug
class PR #104's skip_always_ask carve-out exists to prevent.
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


def test_selectmodel_always_asks_by_default():
    """No skip_always_ask entry — unconditional ask, the standing contract
    this whole override exists for (SVX's live Select Model regression)."""
    _filled, _display_filled, pending = _auto_fill(skip_always_ask=None, governed_ids={1})

    assert "modelSelectionSelectModel_test" not in _filled
    assert any(a.variable_name == "modelSelectionSelectModel_test" for a in pending)


def test_selectmodel_respects_skip_always_ask_carveout_when_governed():
    """A governed catalog that legitimately declared this attr's ask
    suppressed (the native UI never shows it) must get the blind
    first-by-order fallback instead of being forced to always-ask —
    exactly like productSelectionProduct_all's own carve-out."""
    filled, display_filled, pending = _auto_fill(
        skip_always_ask={"modelSelectionSelectModel_test"}, governed_ids={1},
    )

    assert filled.get("modelSelectionSelectModel_test") == "VARIANT_A"
    assert display_filled.get("modelSelectionSelectModel_test") == "Variant A"
    assert not any(a.variable_name == "modelSelectionSelectModel_test" for a in pending)


def test_selectmodel_respects_skip_always_ask_when_ungoverned():
    """An ungoverned selectmodel attr never reaches the governed-blind-
    fallback elif (requires is_governed=True) and falls straight to the
    separate pending-queue guard, which needs the same carve-out on its
    own — must not be asked when skip_always_ask covers it."""
    _filled, _display_filled, pending = _auto_fill(
        skip_always_ask={"modelSelectionSelectModel_test"}, governed_ids=None,
    )

    assert not any(a.variable_name == "modelSelectionSelectModel_test" for a in pending)
