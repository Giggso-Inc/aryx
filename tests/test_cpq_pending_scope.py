"""PROMPT 7 — pending_scope resolve ladder + durable scope retention."""
from __future__ import annotations

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.pending_scope import (
    candidates_from_attr_options,
    clear_pending_scope,
    format_did_you_mean,
    is_confident_scope_suggestion,
    resolve_against_scope,
    set_pending_scope,
)
from aryx.cpq.session_guard import has_consumable_pending_state
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options or [], select_type="single",
    )


# ── Pure ladder ────────────────────────────────────────────────────────────

def test_exact_match():
    r = resolve_against_scope("Premium", ["Standard", "Premium", "Basic"])
    assert r.matched == "Premium"
    assert r.tier == "exact"


def test_partial_federal_in_scope():
    """Live-verified: 'Federal' resolves within a scoped product list."""
    cands = [
        "APX NEXT International (Federal)",
        "APX NEXT (4G LTE Only)",
        "APX 6500",
    ]
    r = resolve_against_scope("Federal", cands)
    assert r.matched == "APX NEXT International (Federal)"
    assert r.tier == "partial"


def test_fuzzy_r7ex_within_scope():
    cands = [
        "SL3500e R7",
        "SL3500e R7EX",
        "SL3500e Standard",
        "APX 6500",
    ]
    r = resolve_against_scope("r7ex", cands)
    assert r.matched is not None
    assert "R7EX" in r.matched.upper() or "r7ex" in r.matched.lower()


def test_miss_returns_suggestions_not_empty_scope():
    cands = ["Alpha One", "Bravo Two", "Charlie Three"]
    r = resolve_against_scope("zzzznotreal", cands)
    assert r.matched is None
    assert r.tier == "miss"
    # Suggestions stay inside scope
    for s in r.suggestions:
        assert s in cands


def test_digit_index():
    r = resolve_against_scope("2", ["A", "B", "C"])
    assert r.matched == "B"


def test_has_consumable_pending_includes_scope():
    assert has_consumable_pending_state({
        "pending_scope_candidates": ["A", "B"],
    })
    assert not has_consumable_pending_state({
        "pending_scope_candidates": [],
        "pending_variables": [],
    })


def test_format_did_you_mean_stays_scoped():
    msg = format_did_you_mean("r7ex", ["SL3500e R7EX", "SL3500e R7"])
    assert "325" not in msg
    assert "R7EX" in msg
    assert "did you mean" in msg.lower() or "Didn't get" in msg or "didn't get" in msg


# ── "did you mean" confidence gating (2026-08-08) ───────────────────────────
# Live bug: resending an entire unrelated sentence as a reply to a pending
# Product question scored just over the bare fuzzy-suggest floor against
# ONE real option purely by coincidental character overlap (both strings
# happen to contain "APX NEXT") -- framing that single weak suggestion as
# a confident "did you mean X?" overstated the actual match quality.

def test_resending_the_original_question_is_not_a_confident_suggestion():
    """A long, unrelated sentence coincidentally overlapping one real
    candidate must land in "miss" tier with a low score -- not confident."""
    cands = [
        "APX NEXT All Band", "APX NEXT XE All Band", "APX NEXT Single Band",
        "APX NEXT XE Single Band", "APX NEXT (International)",
        "APX NEXT XN All Band", "APX NEXT XN Single Band",
    ]
    r = resolve_against_scope("Give me quote of APXNEXT with 10 qty for US", cands)
    assert r.matched is None
    assert r.tier == "miss"
    assert not is_confident_scope_suggestion(r)


def test_ambiguous_substring_tie_is_a_confident_suggestion():
    """Real substring hits, equally specific (so the tie-break can't pick a
    unique winner), are still genuine signal, not coincidental overlap --
    score=1.0, confident."""
    cands = ["APX NEXT Bandone", "APX NEXT Bandtwo"]
    r = resolve_against_scope("APX NEXT Band", cands)
    assert r.tier == "miss"
    assert is_confident_scope_suggestion(r)


def test_format_did_you_mean_low_confidence_single_suggestion_is_not_phrased_as_a_guess():
    msg = format_did_you_mean(
        "Give me quote of APXNEXT with 10 qty for US",
        ["APX NEXT (International)"],
        confident_single=False,
    )
    assert "did you mean" not in msg.lower()
    assert "APX NEXT (International)" in msg


def test_format_did_you_mean_confident_single_suggestion_keeps_the_guess_phrasing():
    msg = format_did_you_mean(
        "Fedral", ["APX NEXT International (Federal)"], confident_single=True,
    )
    assert "did you mean" in msg.lower()
    assert "APX NEXT International (Federal)" in msg


def test_set_clear_scope_on_session():
    s = CpqSession(mode="cpq", product_name="x")
    set_pending_scope(
        s, kind="attr_options", candidates=["A", "B"], origin_question="q",
        attr_vn="priceTier", asked_turn=2,
    )
    assert s.pending_scope_candidates == ["A", "B"]
    assert s.pending_scope_attr_vn == "priceTier"
    d = s.to_dict()
    assert d["pending_scope_candidates"] == ["A", "B"]
    s2 = CpqSession.from_dict(d)
    assert s2.pending_scope_candidates == ["A", "B"]
    clear_pending_scope(s2)
    assert s2.pending_scope_candidates == []


# ── Integration: mismatch keeps constrained product scope ─────────────────

def test_pending_product_mismatch_scoped_reask_not_325(monkeypatch):
    """sl3500e-style constrained list → typo reply → fuzzy apply OR scoped re-ask.

    Never dumps the catalog-wide 325-option Product prompt (APX 6500 examples).
    """
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "ingested_product_alias_map", lambda *a, **k: {},
    )
    monkeypatch.setattr(
        api._cpq_engine, "detect_product_mention", lambda *a, **k: "",
    )
    monkeypatch.setattr(
        api._cpq_engine, "suggest_product_candidates", lambda *a, **k: [],
    )
    monkeypatch.setattr(
        api._cpq_engine, "single_model_variable_name", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        api._cpq_engine, "model_variable_candidates", lambda *a, **k: [],
    )

    scoped = [
        "SL3500e R7", "SL3500e R7EX", "SL3500e Standard", "SL3500e Lite",
    ]
    product = _attr(
        1, "productSelectionProduct_all", "Product",
        options=_opt(*scoped, "APX 6500", "APX 6500Li", "APX 5500"),
    )
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([product], "sl3500e_bom"),
    )
    # Force constraint recompute to the scoped subset
    monkeypatch.setattr(
        api._cpq_engine, "apply_constraint_rules",
        lambda *a, **k: {1: [o.item_value for o in product.options if o.item_value in scoped]},
    )

    session = CpqSession(
        mode="cpq", product_name="sl3500e_bom", country="United States",
        pending_variables=["productSelectionProduct_all"],
        pending_scope_kind="product_options",
        pending_scope_candidates=scoped,
        pending_scope_attr_vn="productSelectionProduct_all",
        pending_scope_asked_turn=2,
        status="configuring", turn=3,
    )
    req = AskRequest(
        question="r7ex", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn(req, object())
    assert resp is not None
    answer = resp["answer"]
    sd = resp["session_data"]
    # Must NOT dump the catalog-wide Product overflow prompt
    assert "325" not in answer
    assert "too many to list" not in answer.lower()
    filled = sd.get("filled", {}).get("productSelectionProduct_all")
    if filled:
        # Fuzzy recovery applied within scope — preferred outcome
        assert "R7EX" in filled.upper() or filled in scoped
        assert filled not in ("APX 6500", "APX 6500Li", "APX 5500")
    else:
        # Scoped re-ask retained the candidate list
        assert sd.get("pending_scope_candidates"), "scope must survive mismatch"
        assert any(c in answer for c in scoped) or "did you mean" in answer.lower() or "didn't get" in answer.lower()


def test_pending_federal_partial_applies(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    options = [
        "APX NEXT International (Federal)",
        "APX NEXT (4G LTE Only)",
        "APX NEXT (4G LTE+5G)",
    ]
    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt(*options))
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([product], "aSTRO25_bom"),
    )
    monkeypatch.setattr(
        api._cpq_engine, "apply_constraint_rules",
        lambda *a, **k: {1: list(options)},
    )

    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        pending_variables=["productSelectionProduct_all"],
        pending_scope_kind="product_options",
        pending_scope_candidates=options,
        pending_scope_attr_vn="productSelectionProduct_all",
        status="configuring", turn=3,
    )
    req = AskRequest(question="Federal", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp is not None
    filled = resp["session_data"]["filled"].get("productSelectionProduct_all")
    assert filled == "APX NEXT International (Federal)"


def test_candidates_from_attr_options_only_includes_display_name():
    """Live-confirmed bug (2026-08-13): item_value was also appended
    whenever it differed from display_name (e.g. item_value "APX NEXT
    MULTI" for the real "APX NEXT All Band" option) -- an internal
    catalog code, never meant to be customer-facing, that leaked into
    the numbered "same list as before" re-ask as if it were a separate,
    legitimate product choice, inflating a real 7-option list into 11.
    """
    options = [
        MenuOption(item_value="APX NEXT ALL BAND", display_name="APX NEXT All Band", order=0),
        MenuOption(item_value="APX NEXT MULTI", display_name="APX NEXT All Band", order=1),
        MenuOption(item_value="APX NEXT INTL FED", display_name="APX NEXT International (Federal)", order=2),
    ]
    cands = candidates_from_attr_options(options)
    assert cands == ["APX NEXT All Band", "APX NEXT All Band", "APX NEXT International (Federal)"]
    assert "APX NEXT MULTI" not in cands
    assert "APX NEXT INTL FED" not in cands


def test_candidates_from_attr_options_respects_constrained_item_values():
    options = [
        MenuOption(item_value="A", display_name="Alpha", order=0),
        MenuOption(item_value="B", display_name="Beta", order=1),
    ]
    cands = candidates_from_attr_options(options, constrained_item_values=["A"])
    assert cands == ["Alpha"]


def test_already_resolved_model_leaf_never_wipes_an_unrelated_pending_scope(monkeypatch):
    """Live-confirmed bug (2026-08-13): the ambiguous-model-leaf
    re-resolution block had no `model_leaf_resolved` short-circuit, so
    once resolved on an earlier turn it kept re-resolving (and calling
    clear_pending_scope) on EVERY subsequent turn, silently wiping an
    unrelated, in-progress Product disambiguation scope -- "now set the
    product" replied to a pending "Product -- choose one" question had
    its 7-item scope silently cleared before ever reaching the
    Product-matching code, turning a should-be-scoped reask into a
    full-catalog one.
    """
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(
        api._cpq_engine, "load_recommendation_and_constraint_rules",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "single_model_variable_name", lambda *a, **k: "")
    # 2+ leaves (ambiguous tree) -- the same shape that originally
    # required disambiguation -- with one matching the already-filled
    # hint, so `_resolved_leaf` is truthy on every turn, not just once.
    monkeypatch.setattr(
        api._cpq_engine, "model_variable_candidates",
        lambda *a, **k: ["aPXNext_BOM", "aPXN70_BOM"],
    )

    scoped = ["APX NEXT All Band", "APX NEXT XE All Band", "APX NEXT Single Band"]
    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt(*scoped))
    monkeypatch.setattr(
        api._cpq_engine, "load_product_config",
        lambda *a, **k: ([product], "aSTRO25_bom"),
    )
    monkeypatch.setattr(
        api._cpq_engine, "apply_constraint_rules",
        lambda *a, **k: {1: [o.item_value for o in product.options]},
    )

    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"_bm_model_variable_name": "aPXNext_BOM"},
        model_leaf_resolved=True,
        pending_variables=["productSelectionProduct_all"],
        pending_scope_kind="product_options",
        pending_scope_candidates=scoped,
        pending_scope_attr_vn="productSelectionProduct_all",
        pending_scope_asked_turn=2,
        status="configuring", turn=3,
    )
    req = AskRequest(
        question="now set the product", workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn(req, object())
    assert resp is not None
    assert resp["session_data"]["pending_scope_candidates"] == scoped
