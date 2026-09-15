"""Regression coverage for CpqSession.product_noise_filter_ready and its
use in _step10_recompute_pending (src/aryx/cpq/state/__init__.py,
src/aryx/api/ask_turn_steps/ask_step10_recompute_pending.py).

Motivating live bug (2026-09-14, "quote for SVX" -> "united states"):
step 1's single-suggestion auto-resolve anchors a product FAMILY
(session.product_name) via a different mechanism than the strict
bm_catalog-leaf disambiguation path that sets model_leaf_resolved.
Catalogs like videoSolutions_BOM never set model_leaf_resolved, so their
own ungoverned "Product"-labeled attr fell through to the full unscoped
option list instead of being treated as noise.
"""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_turn_steps.ask_step10_recompute_pending import _step10_recompute_pending
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options or [], select_type="single",
    )


class _FakeReq:
    workspace_id = 402
    question = "United States"


def _stub_common_engine(monkeypatch, attrs, pending):
    monkeypatch.setattr(api._cpq_engine, "evaluate_rules_loop",
                         lambda *a, **k: (attrs, {}, {}, {}))
    monkeypatch.setattr(api._cpq_engine, "governed_target_ids", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "auto_fill", lambda *a, **k: ({}, {}, list(pending)))
    monkeypatch.setattr(api._cpq_engine, "_load_layout_full_order", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_layout_display_order", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "append_pending_grid_quantities",
                         lambda pending, *a, **k: pending)


# ── CpqSession.product_noise_filter_ready ───────────────────────────────

def test_property_false_when_neither_leaf_nor_family_resolved():
    session = CpqSession()
    assert session.product_noise_filter_ready is False


def test_property_true_via_the_strict_model_leaf_path():
    session = CpqSession(model_leaf_resolved=True)
    assert session.product_noise_filter_ready is True


def test_property_true_via_a_resolved_family_alone_svx_case():
    """The exact motivating gap: model_leaf_resolved never fires for a
    catalog like videoSolutions_BOM, but product_name being anchored at
    all is now enough."""
    session = CpqSession(product_name="videoSolutions_BOM", model_leaf_resolved=False)
    assert session.product_noise_filter_ready is True


# ── _step10_recompute_pending integration ───────────────────────────────

def test_ungoverned_product_attr_dropped_once_family_is_anchored(monkeypatch):
    """videoSolutions_BOM case: family anchored, no bm_catalog leaf
    resolution, "Product" has zero governing rules -- must be dropped
    from pending, not surfaced as a 325-option prompt."""
    product_attr = _attr(1, "productSelectionProduct_all", "Product", options=_opt("A", "B"))
    other_attr = _attr(2, "mountingTypeArray_viSoln", "Mounting Type", options=_opt("X"))
    _stub_common_engine(monkeypatch, [product_attr, other_attr], [product_attr, other_attr])

    session = CpqSession(product_name="videoSolutions_BOM", model_leaf_resolved=False)
    _, _, _, pending, _, _ = _step10_recompute_pending(
        {}, [product_attr, other_attr], session, [], [], [], None, {}, set(), set(),
        [], _FakeReq(), "Svx Video Remote Speaker Microphone",
    )
    pending_vns = {a.variable_name for a in pending}
    assert "productSelectionProduct_all" not in pending_vns
    assert "mountingTypeArray_viSoln" in pending_vns


def test_rule_governed_product_attr_still_asked_apx_next_case(monkeypatch):
    """APX Next case: a real constraint rule targets "Product" -- it
    must still be asked even though a family is anchored, matching
    product_label_noise_vns's own rule_governed_ids exclusion."""
    product_attr = _attr(1, "productSelectionProduct_all", "Product", options=_opt("A", "B"))
    hw_attr = _attr(2, "hWVersion_astro", "Hardware Version", options=_opt("X", "Y"))
    con = ConstraintRule("restrict product by hw version", 2, "X", 1, ["A"])
    _stub_common_engine(monkeypatch, [product_attr, hw_attr], [product_attr, hw_attr])

    session = CpqSession(product_name="aSTRO25_bom", model_leaf_resolved=False)
    _, _, _, pending, _, _ = _step10_recompute_pending(
        {}, [product_attr, hw_attr], session, [], [], [con], None, {}, set(), set(),
        [], _FakeReq(), "aSTRO25_bom",
    )
    pending_vns = {a.variable_name for a in pending}
    assert "productSelectionProduct_all" in pending_vns


def test_ungoverned_product_attr_still_asked_when_nothing_resolved(monkeypatch):
    """Baseline: with no family AND no leaf resolved, the old behavior
    (asking Product unfiltered) is unchanged -- this fix only narrows
    once identity is known some way, never hides noise prematurely."""
    product_attr = _attr(1, "productSelectionProduct_all", "Product", options=_opt("A", "B"))
    _stub_common_engine(monkeypatch, [product_attr], [product_attr])

    session = CpqSession(product_name="", model_leaf_resolved=False)
    _, _, _, pending, _, _ = _step10_recompute_pending(
        {}, [product_attr], session, [], [], [], None, {}, set(), set(),
        [], _FakeReq(), "videoSolutions_BOM",
    )
    pending_vns = {a.variable_name for a in pending}
    assert "productSelectionProduct_all" in pending_vns
