"""Tests for docs/CPQ_AMBIGUOUS_CLARIFY_DISCARDS_RESOLVED_EVIDENCE_PLAN_
2026_08_21.md — two live-reproduced bugs where the system already had the
right answer internally (a gateway-resolved attribute, or an
already-stated value) and threw it away before asking the customer
anything.

Case 1 (Fix 1): "set the Primary Frequency band to UHF band" -> gateway
resolves the ATTRIBUTE confidently (its own rationale says so) but calls
the turn AMBIGUOUS because the VALUE is unclear (UHF R1 vs UHF R2). The
old code discarded the resolved attribute and asked "which attribute",
pulling in unrelated sibling attrs via raw word-overlap ("frequency" is
generic). Fixed: trust `_gw.result.variable_name` when present and real,
routing through `_apply_pending_clarify_resolution` (attribute-scoped)
instead of the generic multi-attribute clarify.

Case 2 (Fix 2): "Set SmartProgramming to 2Yrs" -> resolves to exactly one
real candidate attribute, then jumps straight to "Which value would you
like?" without ever re-attempting to match the already-stated value
("2Yrs") against that attribute's real options. Fixed: reuse
`_apply_pending_clarify_resolution` (already used elsewhere for the
anchor-based case) instead of `_build_no_value_response` directly.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
from aryx.api.ask_pending_clarify.ask_pending_clarify_answer import _set_pending_clarify_and_answer
from aryx.cpq.intent_gateway import GatewayDecision
from aryx.cpq.intent_schema.intent_schema import Confidence, GatewayIntentResult, IntentCategory
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption
from aryx.api import ask_core_helpers as _ask_core_helpers_test_module


def _opt(*pairs: tuple[str, str]) -> list[MenuOption]:
    return [MenuOption(item_value=iv, display_name=dn, order=i) for i, (iv, dn) in enumerate(pairs)]


def _attr(eid, vn, label, options, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=False,
        default_value="", options=options, select_type=select_type,
    )


# ── Fix 1: AMBIGUOUS with a gateway-resolved attribute ──────────────────

def _freq_attrs():
    primary = _attr(
        1, "modelSelectionPrimaryFrequency_astro", "Primary Frequency",
        _opt(("UHF R1", "UHF R1"), ("UHF R2", "UHF R2")),
    )
    band = _attr(
        2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band",
        _opt(("700/800", "700/800 MHz"), ("VHF", "VHF")),
    )
    return [primary, band]


def _ambiguous_decision(vn: str, clarifying_question: str) -> GatewayDecision:
    return GatewayDecision(
        action="clarify",
        result=GatewayIntentResult(
            intent_category=IntentCategory.AMBIGUOUS, confidence=Confidence.LOW,
            variable_name=vn, evidence_span="", clarifying_question=clarifying_question,
            rationale="attribute is the clear target; value is ambiguous",
        ),
    )


def test_ambiguous_with_resolved_attr_and_matching_value_applies_directly(monkeypatch):
    """The core repro: gateway names the right attribute; the message also
    happens to contain a real, exact value -- must apply directly, never
    ask anything."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    attrs = _freq_attrs()
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: _ambiguous_decision(
            "modelSelectionPrimaryFrequency_astro",
            "Did you mean Primary Frequency or Frequency Band?",
        ),
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                "modelSelectionFrequencyBandMsl_astro": "700/800"},
        display_filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                         "modelSelectionFrequencyBandMsl_astro": "700/800 MHz"},
    )
    req = AskRequest(question="set the primary frequency to UHF R2", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["filled"]["modelSelectionPrimaryFrequency_astro"] == "UHF R2"
    assert "Which attribute did you mean" not in resp.get("answer", "")


def test_ambiguous_with_resolved_attr_and_unmatched_value_asks_scoped_to_that_one_attr(monkeypatch):
    """Value genuinely doesn't resolve ("UHF band" matches neither real
    option) -- must still ask, but scoped to Primary Frequency ALONE, never
    re-opening the old multi-attribute "which attribute" disambiguation
    that pulled in Frequency Band via raw word overlap on "frequency"."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    attrs = _freq_attrs()
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: _ambiguous_decision(
            "modelSelectionPrimaryFrequency_astro",
            "Did you mean Primary Frequency or Frequency Band?",
        ),
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                "modelSelectionFrequencyBandMsl_astro": "700/800"},
        display_filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                         "modelSelectionFrequencyBandMsl_astro": "700/800 MHz"},
    )
    req = AskRequest(question="set the primary frequency band to UHF band", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    answer = resp.get("answer", "")
    assert "Primary Frequency" in answer
    assert "Which attribute did you mean" not in answer
    assert "Frequency Band" not in answer, (
        "the old bug pulled in this unrelated sibling attribute via raw "
        "word-overlap on the generic word 'frequency'"
    )
    # Still unchanged -- nothing was silently applied.
    assert resp["session_data"]["filled"]["modelSelectionPrimaryFrequency_astro"] == "UHF R1"


def test_ambiguous_with_resolved_attr_currently_hidden_falls_through_to_clarify(monkeypatch):
    """Raven review on PR #264 (finding M1): the gateway's resolved
    variable_name is trusted and routed straight into
    _apply_pending_clarify_resolution without checking whether it's
    currently hidden for this product -- unlike the sibling
    _set_pending_clarify_and_answer path, which was already safe by
    construction. A hidden-but-still-filled attribute (e.g. hidden after
    being set earlier in the session, or a stale/hallucinated gateway
    resolution) must never be silently changed via this fast path; it
    must fall through to the same hidden-aware clarify flow every other
    candidate uses."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    attrs = _freq_attrs()
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: _ambiguous_decision(
            "modelSelectionPrimaryFrequency_astro",
            "Did you mean Primary Frequency or Frequency Band?",
        ),
    )
    # Primary Frequency is currently hidden for this product/config --
    # e.g. a hiding rule fired after it was filled earlier in the session.
    monkeypatch.setattr(
        api._cpq_engine, "apply_hiding_rules",
        lambda *a, **k: (
            [a for a in attrs if a.variable_name != "modelSelectionPrimaryFrequency_astro"],
            [],
            {"modelSelectionPrimaryFrequency_astro"},
        ),
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                "modelSelectionFrequencyBandMsl_astro": "700/800"},
        display_filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                         "modelSelectionFrequencyBandMsl_astro": "700/800 MHz"},
    )
    req = AskRequest(question="set the primary frequency to UHF R2", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    session_out = resp["session_data"]
    # Must NOT have been silently applied via the fast path -- the
    # hidden attribute's value is completely untouched.
    assert session_out["filled"]["modelSelectionPrimaryFrequency_astro"] == "UHF R1"
    assert "modelSelectionPrimaryFrequency_astro" not in session_out["pending_clarify_vns"]
    # With the hidden attribute correctly excluded, Frequency Band is the
    # only real candidate left -- narrows to a single-candidate resolution
    # (asking for ITS value) rather than a "which attribute" disambiguation
    # that could still list a hidden attribute.
    assert session_out["pending_change_no_value_vn"] == "modelSelectionFrequencyBandMsl_astro"


def test_ambiguous_with_no_resolved_attr_keeps_existing_multi_attribute_behavior(monkeypatch):
    """A genuinely attribute-level ambiguity (no variable_name at all) must
    be completely unaffected by this fix."""
    monkeypatch.setattr(_ask_core_helpers_test_module, "_persist_cpq_history", lambda *a, **k: None)
    attrs = _freq_attrs()
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: GatewayDecision(
            action="clarify",
            result=GatewayIntentResult(
                intent_category=IntentCategory.AMBIGUOUS, confidence=Confidence.LOW,
                variable_name=None, evidence_span="",
                clarifying_question="Did you mean Primary Frequency or Frequency Band?",
                rationale="genuinely unclear which attribute",
            ),
        ),
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                "modelSelectionFrequencyBandMsl_astro": "700/800"},
        display_filled={"modelSelectionPrimaryFrequency_astro": "UHF R1",
                         "modelSelectionFrequencyBandMsl_astro": "700/800 MHz"},
    )
    req = AskRequest(question="set the frequency to something else", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    # Unchanged existing behavior: a real multi-attribute clarify prompt.
    assert resp["session_data"]["pending_clarify_vns"]


# ── Fix 2: single-candidate clarify with an already-stated value ────────

def test_single_candidate_clarify_still_asks_for_value_reverted_fix_2():
    """Fix 2 (auto-apply an already-stated value on a single-candidate
    clarify) was implemented, then REVERTED after discovering it conflicts
    with the "blanket LLM-as-final-verdict" mutating-disagreement safety
    checkpoint (test_cpq_llm_verdict_checkpoint_2026_08_13.py) -- this
    branch is reached specifically when the gateway called the turn
    AMBIGUOUS or disagreed with the deterministic detector, so re-running
    that same deterministic match here (even with a real, matching value
    stated) would silently dispatch a change the gateway had just declined
    to trust. This test pins down the CURRENT, deliberately-kept-safe
    behavior: even a message stating a real, valid value still gets asked
    for that value again. The SmartProgramming-shaped bug this would have
    fixed is documented as a known, still-open gap in
    docs/CPQ_AMBIGUOUS_CLARIFY_DISCARDS_RESOLVED_EVIDENCE_PLAN_2026_08_21.md."""
    attr = _attr(1, "anywhereProgramming_astro", "SmartProgramming",
                 _opt(("1 YEAR", "1 Year"), ("2 YEAR", "2 Year")))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom",
        filled={"anywhereProgramming_astro": "1 YEAR"},
        display_filled={"anywhereProgramming_astro": "1 Year"},
    )
    req = AskRequest(question="Set SmartProgramming to 2 Year", workspace_id=1,
                      session_data=session.to_dict())
    result = _set_pending_clarify_and_answer(
        req, session, [attr],
        original_question=req.question,
        clarifying_question="Did you mean SmartProgramming?",
        con_rules=[], bml_eval=None, hiding_rules=[], rec_rules=[],
    )
    assert result["session_data"]["filled"]["anywhereProgramming_astro"] == "1 YEAR"
    assert "Which value would you like" in result.get("answer", "")
    assert "SmartProgramming" in result.get("answer", "")
