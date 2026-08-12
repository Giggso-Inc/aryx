"""Regression coverage for the 2026-07-28 fix session, plus broader scenario
coverage for LLM-first intent dispatch, mid-session product/attribute
changes, Q&A, and quote/approval — requested alongside the fixes.

Section A pins each of the day's confirmed root causes so none can regress
silently. Section B exercises the surrounding conversational flows the day's
work touched (LLM-first classification, session state changes, Q&A during
active configuration, and the quote/approval submission path) using the
same lightweight monkeypatch-the-loaders pattern as test_cpq_product_switch.py
— no real Postgres/FalkorDB required.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    _dispatch_intent_result,
    _handle_cpq_qa,
    _resolve_target_description,
    _run_cpq_turn,
    _with_classify_usage,
)
from aryx.cpq.bml import BmlEvaluator, evaluate_tier1
from aryx.cpq.engine import CpqEngine
from aryx.cpq.intent_schema import ChangeTarget, Confidence, IntentCategory, IntentResult
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


# ═══════════════════════════════════════════════════════════════════════
# Section A — regression pins for today's 6 fixes
# ═══════════════════════════════════════════════════════════════════════

# ── A1. STEP 5: a stuck pending attr must not swallow a genuine new
# change request naming a DIFFERENT, real attr (fa65b0d) ────────────────

def test_stuck_pending_attr_does_not_block_a_new_change_request(monkeypatch):
    """Product is permanently stuck pending (325 options, nothing resolves
    it). The customer's next message names a totally different, already-
    filled attr with a change verb — this must fall through to the
    change-request handler, not be swallowed as a failed answer attempt
    to the stuck Product question."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt("A", "B", "C"))
    solution = _attr(2, "solutionType", "Solution Type", options=_opt("RadioCentral", "CloudRC"))
    attrs = [product, solution]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"solutionType": "RadioCentral"},
        display_filled={"solutionType": "RadioCentral"},
        pending_variables=["productSelectionProduct_all"],
        status="configuring", turn=2,
    )
    req = AskRequest(question="change the solution type to CloudRC",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())

    assert resp, "engine returned no response"
    assert "productSelectionProduct_all" not in resp["answer"], (
        "must not report a failed match against the stuck Product attr"
    )
    # Not just "didn't error" — the actual new request must have been
    # applied, not silently dropped.
    assert resp["session_data"]["filled"].get("solutionType") == "CloudRC"
    assert resp["session_data"]["pending_variables"] == [
        "productSelectionProduct_all"
    ], "the stuck attr itself must remain pending — only skipped as the LOCK target this turn"


def test_stuck_pending_attr_still_locks_a_genuine_bare_reply(monkeypatch):
    """Sibling case, opposite outcome: when the message is NOT a new
    change request (no change verb, no other real attr named), STEP 5's
    original lock-the-pending-answer behavior must still fire —
    _looks_like_new_request must not become "never lock anything"."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    attrs = [battery]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        pending_variables=["batteryType_astro"], status="configuring", turn=2,
    )
    req = AskRequest(question="EXTENDED", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["session_data"]["filled"].get("batteryType_astro") == "EXTENDED"
    assert resp["session_data"]["pending_variables"] == []


# ── A2. Rarity-weighted _resolve_target_description (fa65b0d) ──────────

def test_resolve_target_description_prefers_rare_word_over_shared_generic_one():
    """"Solution Type" must resolve uniquely to solutionTypeDevices even
    though many sibling attrs also carry the generic word "type" — raw
    overlap-count scoring previously tied them all together."""
    target = _attr(1, "solutionTypeDevices_astro", "Solution Type")
    decoys = [
        _attr(2, "beltClipType_astro", "Carry Type"),
        _attr(3, "customerType", "Customer Type"),
        _attr(4, "modelSelectionOrderType_astro", "Order Type"),
        _attr(5, "modelSelectionKeypadType_astro", "Keypad Type"),
    ]
    attrs = [target] + decoys
    resolved, candidates = _resolve_target_description("Solution Type", attrs)
    assert resolved is target
    assert len(candidates) >= 2, "decoys sharing 'type' must still surface as candidates"


def test_resolve_target_description_returns_none_on_a_genuine_tie():
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    resolved, candidates = _resolve_target_description("Product", [a, b])
    assert resolved is None
    assert len(candidates) == 2


# ── A3. Real token usage threaded through the older change-intent
# fallback (9144d07) — _with_classify_usage's own contract ──────────────

def test_with_classify_usage_adds_real_tokens_and_relabels_model():
    result = {
        "answer": "ok", "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                                    "menial_model": "cpq-engine"},
    }
    out = _with_classify_usage(result, 993, 36)
    assert out["usage"]["prompt_tokens"] == 993
    assert out["usage"]["completion_tokens"] == 36
    assert out["usage"]["menial_model"] == "cpq-llm-first"


def test_with_classify_usage_is_a_noop_when_no_tokens_spent():
    result = {"answer": "ok", "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
    out = _with_classify_usage(result, 0, 0)
    assert out is result
    assert out["usage"]["prompt_tokens"] == 0


def test_with_classify_usage_passes_through_none():
    assert _with_classify_usage(None, 10, 5) is None


# ── A4. product_label_noise_vns scoping (708c33e) ───────────────────────

def test_product_label_noise_vns_excludes_a_rule_governed_product_attr():
    """A "Product"-labeled attr with a real constraint rule targeting it
    (APX Next's case) must NEVER be treated as noise, even when
    model_leaf_resolved fires."""
    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt("A", "B"))
    hw = _attr(2, "hWVersion_astro", "Hardware Version", options=_opt("X", "Y"))
    con = ConstraintRule("restrict product by hw version", 2, "X", 1, ["A"])
    noise = CpqEngine.product_label_noise_vns([product, hw], [], [], [con])
    assert "productSelectionProduct_all" not in noise


def test_product_label_noise_vns_includes_a_genuinely_ungoverned_product_attr():
    """A "Product"-labeled attr with NO rule targeting it at all (the real
    CommandCentral case this mechanism was built for) stays noise."""
    product = _attr(1, "productSelectionProduct_all", "Product", options=_opt("A", "B"))
    other = _attr(2, "someOtherAttr", "Other")
    con = ConstraintRule("unrelated rule", 2, "X", 2, ["A"])  # targets `other`, not Product
    noise = CpqEngine.product_label_noise_vns([product, other], [], [], [con])
    assert "productSelectionProduct_all" in noise


# ── A5. Tier-1 blocker scoping + block-comment stripping (66baae5) ─────

def test_tier1_resolves_a_script_with_a_dead_commented_util_call():
    """The real "Restrict APX Next Product Selection based on HW Version
    selection" script pattern: a live if/else returnVal assignment, plus a
    dead /* */-commented scratch block and a trailing live util.* call
    that have nothing to do with the branch logic. Both must be ignored
    by the Tier-1 parser now, not force the whole script to Tier 2."""
    script = '''returnVal = "";
if( (hWVersion_astro=="NEXT ENHANCED LTE PLUS 5G")){
    returnVal = "APX NEXT ENHANCED|^|APX NEXT XE 4G LTE PLUS 5G";
}
else{
    returnVal = "|^|APX NEXT SINGLE BAND|^|APX NEXT XE SINGLE BAND";
}

/*
if(not isnull(usersessionget("TE_FLAG"))) {
  setValResp = util.setConstraintValuesInSession("productSelectionProduct_all", returnVal, "ALLOW");
}
*/

if(sessionVariable_TER <> ""){
  setValResp = util.setConstraintValuesInSession("productSelectionProduct_all", returnVal, "ALLOW");
}

return returnVal;'''
    allowed, blocked = evaluate_tier1(script, {"hWVersion_astro": "NEXT ENHANCED LTE PLUS 5G"})
    assert blocked is False
    assert allowed == ["APX NEXT ENHANCED", "APX NEXT XE 4G LTE PLUS 5G"]

    allowed_else, blocked_else = evaluate_tier1(script, {"hWVersion_astro": "anything else"})
    assert blocked_else is False
    assert allowed_else == ["APX NEXT SINGLE BAND", "APX NEXT XE SINGLE BAND"]


def test_tier1_still_blocks_a_script_whose_live_branch_needs_a_loop():
    """A genuine unsupported construct INSIDE the branch body (not a dead
    comment or unrelated trailing statement) must still defer to Tier 2 —
    the scoping fix narrows WHERE the blocker check applies, it doesn't
    remove the check."""
    script = '''if (x=="Y") {
    for (i = 0; i < 5; i = i + 1) { returnVal = returnVal + "A"; }
}
else {
    returnVal = "B";
}
return returnVal;'''
    _allowed, blocked = evaluate_tier1(script, {"x": "Y"})
    assert blocked is False  # not "unresolvable due to missing var" — genuinely unparseable
    result, _ = evaluate_tier1(script, {"x": "Y"})
    assert result is None


# ── A6. bm_config_att_override menu items are merged into the base
# attr's option list (d42f47e) ──────────────────────────────────────────

class _OverrideAwareReader:
    """Minimal reader double exposing exactly what load_product_config
    needs: a base bm_config_attr entity whose own menu neighbors are
    stale/incomplete, plus a bm_config_att_override entity (same native
    attribute_id) whose neighbors carry the missing option."""

    def __init__(self):
        self.BASE_EID = 100
        self.OVERRIDE_EID = 200
        self.BASE_MENU_A = 300  # stale list: only "A"
        self.OVERRIDE_MENU_A = 400  # override list: "A" (canonical display) + "B"
        self.OVERRIDE_MENU_B = 401

    def distinct_types(self):
        return ["FooConfigBmConfigAttr", "FooConfigBmConfigAttOverride", "FooConfigBmMenuItem"]

    def find_entities(self, ontology_type=None, limit=500, offset=0, name=None):
        if offset > 0:
            return []
        if ontology_type == "FooConfigBmConfigAttr":
            return [{"id": self.BASE_EID, "type": ontology_type}]
        if ontology_type == "FooConfigBmConfigAttOverride":
            return [{"id": self.OVERRIDE_EID, "type": ontology_type}]
        return []

    def neighbors(self, eid):
        if eid == self.BASE_EID:
            return [{"id": self.BASE_MENU_A, "type": "FooConfigBmMenuItem"}]
        if eid == self.OVERRIDE_EID:
            return [
                {"id": self.OVERRIDE_MENU_A, "type": "FooConfigBmMenuItem"},
                {"id": self.OVERRIDE_MENU_B, "type": "FooConfigBmMenuItem"},
            ]
        return []


def test_override_menu_items_are_merged_with_override_display_winning(monkeypatch):
    reader = _OverrideAwareReader()
    engine = CpqEngine()

    pg_by_id = {
        reader.BASE_EID: {
            "id": "999", "variable_name": "productSelectionProduct_all",
            "default_value": "", "required": "0", "hidden": "0", "order_number": "1",
            "menu_type": "1",
        },
        reader.OVERRIDE_EID: {"attribute_id": "999"},
        reader.BASE_MENU_A: {"item_value": "A", "item_text": "Stale A Display", "order_number": "1"},
        reader.OVERRIDE_MENU_A: {"item_value": "A", "item_text": "Canonical A Display", "order_number": "1"},
        reader.OVERRIDE_MENU_B: {"item_value": "B", "item_text": "B Display", "order_number": "2"},
    }
    monkeypatch.setattr(engine, "_batch_fetch", lambda ids, ws: {i: pg_by_id.get(i, {}) for i in ids})
    monkeypatch.setattr(engine, "_scope_to_catalog",
                         lambda reader, ws, types, hint: (types, "FooConfig"))
    monkeypatch.setattr("aryx.cpq.engine.get_cpq_rdb", lambda: type(
        "R", (), {"fetch_attr_set_assoc": staticmethod(lambda *a, **k: {})})())

    attrs, _name = engine.load_product_config(reader, workspace_id=1, product_hint="Foo")
    assert len(attrs) == 1
    opts = {o.item_value: o.display_name for o in attrs[0].options}
    assert opts == {"A": "Canonical A Display", "B": "B Display"}, (
        "override's display must win for a shared item_value, and the "
        "override-only option must be present"
    )


# ═══════════════════════════════════════════════════════════════════════
# Section B — LLM-first intent, session change, Q&A, and quote/approval
# ═══════════════════════════════════════════════════════════════════════

def _rules_setup(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])


# ── B1. LLM-first intent dispatch ───────────────────────────────────────

def test_llm_first_change_request_dispatches_and_reports_real_usage(monkeypatch):
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval", turn=3)
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_REQUEST, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Solution Type", new_value_description="CloudRC"),
        rationale="named attr + value",
    )
    with patch("aryx.api.ask_api._cpq_engine.build_bml_evaluator", return_value=BmlEvaluator({})):
        resp = _dispatch_intent_result(
            req, session, [solution], result, [], [], [], BmlEvaluator({}),
            classify_prompt_tokens=800, classify_completion_tokens=40,
        )
    assert resp is not None
    assert resp["usage"]["prompt_tokens"] == 800
    assert resp["usage"]["menial_model"] == "cpq-llm-first"
    assert session.filled["solutionTypeDevices_astro"] == "CloudRC"


def test_llm_first_ambiguous_without_clarifying_question_falls_through():
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="hmm", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(category=IntentCategory.AMBIGUOUS, confidence=Confidence.LOW,
                           clarifying_question=None, rationale="unclear")
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is None


def test_llm_first_ambiguous_with_clarifying_question_asks_it():
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="hmm", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.AMBIGUOUS, confidence=Confidence.MEDIUM,
        clarifying_question="Did you mean to change Solution Type or Hardware Version?",
        rationale="two plausible targets",
    )
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None,
                                    classify_prompt_tokens=50, classify_completion_tokens=10)
    assert resp is not None
    assert "Solution Type" in resp["answer"]
    assert resp["usage"]["prompt_tokens"] == 50


# docs/config_consistency_issues_2026-07-30.md issue 1 — a change request
# landing on a currently-hidden-for-this-product attribute (live case:
# VHF written to modelSelectionFrequencyBandMsl_astro, gated OFF for
# Single-Band products) because it remained a valid disambiguation
# candidate right alongside the correct, visible attribute.

def test_llm_first_ambiguous_excludes_hidden_attr_from_clarify_candidates():
    family = _attr(1, "productFamily_astro", "Product Family")
    freq_visible = _attr(2, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                          options=_opt("700/800 MHz", "VHF"))
    freq_plus = _attr(3, "modelSelectionFrequencyBandPlus_astro", "Additional Frequency Bands",
                       options=_opt("700/800 MHz +", "VHF +"))
    freq_hidden = _attr(4, "modelSelectionFrequencyBandMsl_astro", "Frequency Band",
                         options=_opt("VHF", "UHF"))
    attrs = [family, freq_visible, freq_plus, freq_hidden]
    hide_rule = HidingRule(
        rule_name="Hide Msl variant for Single Band",
        condition_attr_id=1, condition_value="SINGLE_BAND",
        target_attr_id=4, hide=True,
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
        filled={"productFamily_astro": "SINGLE_BAND",
                "modelSelectionFrequencyBands_astro": "700/800 MHz",
                "modelSelectionFrequencyBandPlus_astro": "700/800 MHz +"},
        display_filled={"modelSelectionFrequencyBands_astro": "700/800 MHz",
                         "modelSelectionFrequencyBandPlus_astro": "700/800 MHz +"},
    )
    req = AskRequest(question="add VHF (136-174 MHz) as frequency bands",
                      workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.AMBIGUOUS, confidence=Confidence.MEDIUM,
        clarifying_question="Did you mean Frequency Bands or Additional Frequency Bands?",
        rationale="ambiguous frequency attribute",
    )
    resp = _dispatch_intent_result(
        req, session, attrs, result, [hide_rule], [], [], None,
    )
    assert resp is not None
    assert "modelSelectionFrequencyBandMsl_astro" not in session.pending_clarify_vns, (
        "a hidden-for-this-product attribute must never be offered as a "
        "disambiguation candidate"
    )
    assert set(session.pending_clarify_vns) == {
        "modelSelectionFrequencyBands_astro", "modelSelectionFrequencyBandPlus_astro",
    }


# docs/config_consistency_issues_2026-07-30.md issue 4 — a bare value reply
# ("VHF") to a "which attribute did you mean?" clarify is a legal option on
# SEVERAL candidates at once (confirmed live against the real APX NEXT
# catalog: Frequency Bands, Frequency Band/Msl, Primary Frequency, and
# Secondary Frequency all accept "VHF"), so it can't disambiguate on its
# own — but once the customer already resolved an earlier clarify to one
# specific candidate, THAT anchor should break the tie instead of
# re-asking the same question forever (live-confirmed infinite loop).

def test_dispatch_intent_result_resolves_directly_via_remembered_clarify_anchor():
    bands = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                   options=_opt("700/800 MHZ", "VHF", "UHF"))
    msl = _attr(2, "modelSelectionFrequencyBandMsl_astro", "Frequency Band",
                options=_opt("700/800 MHZ", "VHF", "UHF"), select_type="multi")
    primary = _attr(3, "modelSelectionPrimaryFrequency_astro", "Primary Frequency",
                     options=_opt("700/800 MHZ", "VHF"))
    secondary = _attr(4, "modelSelectionSecondaryFrequency_astro", "Secondary Frequency",
                       options=_opt("700/800 MHZ", "VHF"))
    attrs = [bands, msl, primary, secondary]
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
        filled={"modelSelectionFrequencyBands_astro": "700/800 MHZ"},
        display_filled={"modelSelectionFrequencyBands_astro": "700/800 MHz"},
        # Customer already picked "Frequency Bands" from an earlier clarify.
        last_clarified_attr_vn="modelSelectionFrequencyBands_astro", last_clarified_turn=3,
        turn=5,
    )
    req = AskRequest(question="VHF", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.AMBIGUOUS, confidence=Confidence.MEDIUM,
        clarifying_question=(
            "Did you mean Secondary Frequency, Primary Frequency, "
            "Frequency Bands, or Frequency Band?"
        ),
        rationale="VHF matches several frequency-band-ish attrs",
    )
    resp = _dispatch_intent_result(
        req, session, attrs, result, [], [], [], None,
    )
    assert resp is not None
    # Resolved to the remembered attribute directly — never re-asked "which
    # attribute did you mean?" a second time. "VHF" alone isn't parsed as a
    # change-with-value (no verb/target phrasing), so this lands on the
    # normal "which value for Frequency Bands?" follow-up scoped to the
    # CORRECT attribute, not a fresh multi-way clarify and not a write into
    # the wrong sibling (modelSelectionFrequencyBandMsl_astro also legally
    # accepts "VHF" — that's exactly the ambiguity the anchor must avoid).
    assert session.pending_clarify_vns == []
    assert "Frequency Bands" in resp["answer"]
    assert session.filled.get("modelSelectionFrequencyBands_astro") == "700/800 MHZ"
    assert "modelSelectionFrequencyBandMsl_astro" not in session.filled_multi


def test_match_pending_clarify_reply_stays_ambiguous_without_an_anchor():
    """No remembered anchor + value shared by 2+ candidates -> never guess,
    same 'never guess' discipline as everywhere else in this engine."""
    bands = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                   options=_opt("700/800 MHZ", "VHF"))
    primary = _attr(2, "modelSelectionPrimaryFrequency_astro", "Primary Frequency",
                     options=_opt("700/800 MHZ", "VHF"))
    session = CpqSession(mode="cpq")
    with patch.object(
        api, "_llm_classify_pending_clarify_reply", return_value=("unclear", None),
    ) as mock_llm:
        status, vn = api._match_pending_clarify_reply("VHF", [bands, primary], session, 1)
    assert (status, vn) == ("unclear", None)
    mock_llm.assert_called_once()


def test_match_pending_clarify_reply_resolves_unique_value_without_an_anchor():
    """No anchor needed when the value is unique across candidates."""
    bands = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                   options=_opt("700/800 MHZ", "VHF"))
    carry = _attr(2, "beltClipType_astro", "Carry Type",
                   options=_opt("Plastic Holster", "Hard Leather Case"))
    session = CpqSession(mode="cpq")
    status, vn = api._match_pending_clarify_reply("VHF", [bands, carry], session, 1)
    assert (status, vn) == ("resolved", "modelSelectionFrequencyBands_astro")


def test_llm_first_out_of_scope_answers_without_touching_config():
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
                         filled={"a": "b"})
    req = AskRequest(question="what's the weather", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(category=IntentCategory.OUT_OF_SCOPE, confidence=Confidence.HIGH,
                           rationale="unrelated to quoting")
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is not None
    assert "outside" in resp["answer"].lower()
    assert session.filled == {"a": "b"}, "out-of-scope must never mutate config state"


def test_llm_first_change_target_without_value_asks_which_value():
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval")
    req = AskRequest(question="change the solution type", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_TARGET_WITHOUT_VALUE, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Solution Type", new_value_description=None),
        rationale="named attr, no value",
    )
    with patch("aryx.api.ask_api._cpq_engine.build_bml_evaluator", return_value=BmlEvaluator({})):
        resp = _dispatch_intent_result(
            req, session, [solution], result, [], [], [], BmlEvaluator({}),
            classify_prompt_tokens=200, classify_completion_tokens=15,
        )
    assert resp is not None
    assert "Solution Type" in resp["answer"]
    assert session.pending_change_no_value_vn == "solutionTypeDevices_astro"


def test_llm_first_attr_query_dispatches_on_high_confidence():
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2:
    ATTR_QUERY with HIGH confidence and a resolvable target must dispatch
    to the same _build_attr_query_response the regex path shares."""
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="configuring")
    req = AskRequest(question="what are the options for solution type?", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_QUERY, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Solution Type", new_value_description=None),
        rationale="attr query",
    )
    with patch("aryx.api.ask_api._cpq_engine.build_bml_evaluator", return_value=BmlEvaluator({})):
        resp = _dispatch_intent_result(
            req, session, [solution], result, [], [], [], BmlEvaluator({}),
            classify_prompt_tokens=100, classify_completion_tokens=10,
        )
    assert resp is not None
    assert "Solution Type" in resp["answer"]
    assert "RadioCentral" in resp["answer"]
    assert resp["tools_called"] == ["cpq_attr_query(solutionTypeDevices_astro)"]


def test_llm_first_attr_query_medium_confidence_falls_through():
    """ATTR_QUERY has no deterministic-agreement cross-check (not in
    intent_gateway.MUTATING_CATEGORIES), so it requires HIGH confidence
    specifically -- MEDIUM must defer to the regex path exactly like LOW
    already does everywhere else (residual-risk mitigation #1)."""
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="configuring")
    req = AskRequest(question="what are the options for solution type?", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_QUERY, confidence=Confidence.MEDIUM,
        target=ChangeTarget(target_description="Solution Type", new_value_description=None),
        rationale="attr query",
    )
    resp = _dispatch_intent_result(req, session, [solution], result, [], [], [], None)
    assert resp is None


def test_llm_first_attr_query_unresolvable_target_falls_through():
    """Two attrs share the description word -- no unique resolution ->
    dispatch must return None, never silently guess one, same discipline
    as the CHANGE_TARGET_WITHOUT_VALUE case above."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="configuring")
    req = AskRequest(question="what are the product options?", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_QUERY, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Product", new_value_description=None),
        rationale="attr query",
    )
    resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    assert resp is None


def test_llm_first_unresolvable_target_falls_through_never_guesses():
    """Two attrs share the description word — no unique resolution ->
    dispatch must return None (fall through to deterministic path),
    never silently guess one."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="change product", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_TARGET_WITHOUT_VALUE, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Product", new_value_description=None),
        rationale="named attr",
    )
    resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    assert resp is None


# ── B1b. QA issue #2/#3 (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_
# ISSUE.md §10): pending "which value?" decline + retry-loses-scope fixes ──

def test_pending_change_no_value_decline_leaves_value_unchanged(monkeypatch):
    """"I don't want to change product" after a "which value?" ask must
    cancel the change and keep the current value — not be mismatched as
    an attempted (and failing) Product value."""
    _rules_setup(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [hw]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"hWVersion_astro": "H1"},
                         display_filled={"hWVersion_astro": "H1"},
                         pending_change_no_value_vn="hWVersion_astro",
                         country="United States", status="configuring", turn=3)
    req = AskRequest(question="I don't want to change hardware version",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["session_data"]["filled"].get("hWVersion_astro") == "H1", (
        "decline must never overwrite the current value"
    )
    assert resp["session_data"]["pending_change_no_value_vn"] == ""
    assert resp["tools_called"] == ["cpq_change_declined()"]


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — external
# review found the decline check fired even when a real replacement value
# was stated in the same message ("I don't want Standard; use Premium").
# Fixed by trying a real value match FIRST — a match always wins over
# decline phrasing.

def test_pending_change_no_value_compound_decline_with_replacement_resolves_to_value(monkeypatch):
    """"I don't want Standard, use Premium" must resolve to Premium —
    NOT be misread as a pure cancellation just because "don't want"
    appears in the text."""
    _rules_setup(monkeypatch)
    tier = _attr(1, "priceTier_astro", "Price Tier", options=_opt("Standard", "Premium"))
    attrs = [tier]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"priceTier_astro": "Standard"},
                         display_filled={"priceTier_astro": "Standard"},
                         pending_change_no_value_vn="priceTier_astro",
                         country="United States", status="configuring", turn=3)
    req = AskRequest(question="I don't want Standard, use Premium",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["tools_called"] != ["cpq_change_declined()"], (
        "a stated replacement value must win over decline phrasing"
    )
    assert resp["session_data"]["filled"].get("priceTier_astro") == "Premium"


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §15 — 2 more
# review findings on this same flow.

def test_pending_change_no_value_prefer_over_resolves_to_wanted_value(monkeypatch):
    """"Prefer Premium over Standard" must resolve to Premium, not the
    rejected value — live-confirmed this previously resolved to Standard."""
    _rules_setup(monkeypatch)
    tier = _attr(1, "priceTier_astro", "Price Tier", options=_opt("Standard", "Premium"))
    attrs = [tier]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"priceTier_astro": "Standard"},
                         display_filled={"priceTier_astro": "Standard"},
                         pending_change_no_value_vn="priceTier_astro",
                         country="United States", status="configuring", turn=3)
    req = AskRequest(question="prefer Premium over Standard",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["session_data"]["filled"].get("priceTier_astro") == "Premium"


def test_pending_change_no_value_decline_survives_constraint_engine_failure(monkeypatch):
    """A pure "I don't want to change it" must remain a harmless no-op even
    if constraint recomputation itself raises — it must never crash the
    turn just because the rule engine is unhappy about something unrelated."""
    _rules_setup(monkeypatch)
    hw = _attr(1, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [hw]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    def _raises(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(api._cpq_engine, "apply_constraint_rules", _raises)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"hWVersion_astro": "H1"},
                         display_filled={"hWVersion_astro": "H1"},
                         pending_change_no_value_vn="hWVersion_astro",
                         country="United States", status="configuring", turn=3)
    req = AskRequest(question="I don't want to change hardware version",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["tools_called"] == ["cpq_change_declined()"]
    assert resp["session_data"]["filled"].get("hWVersion_astro") == "H1"


def test_pending_change_no_value_retry_keeps_constrained_option_scope(monkeypatch):
    """After a failed-match retry, the re-shown option list must stay
    scoped to the SAME constrained set the original "which value?" ask
    used — not fall back to every option on the attribute (e.g. the full
    cross-family catalog)."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    family = _attr(1, "familyAstro", "Family", options=_opt("APX_NEXT", "APX_LEGACY"))
    hw = _attr(2, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [family, hw]
    con_rule = ConstraintRule(
        rule_name="scope hardware to family",
        condition_attr_id=1, condition_value="APX_NEXT",
        target_attr_id=2, allowed_values=["H1"],
    )
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], [con_rule]))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"familyAstro": "APX_NEXT"},
                         display_filled={"familyAstro": "APX_NEXT"},
                         pending_change_no_value_vn="hWVersion_astro",
                         country="United States", status="configuring", turn=3)
    req = AskRequest(question="totally unmatched gibberish value",
                      workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert "H1" in resp["answer"]
    assert "H45" not in resp["answer"], (
        "retry must stay scoped to the constrained set, not fall back to "
        "every option on the attribute"
    )


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §11 — live bug
# (2026-07-29): the first bom_gate fix made `recheck_constraints` actually
# reachable, and it started hard-blocking `confirm` on real (but auto-fixable)
# stale constraint values — e.g. Carry Type/Frequency Bands auto-filled
# before Product narrowed their allowed set. Per explicit product decision,
# these must auto-clear + re-ask instead of hard-blocking.

def test_confirm_auto_clears_stale_constraint_value_and_reasks(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    family = _attr(1, "familyAstro", "Family", options=_opt("APX_NEXT", "APX_LEGACY"))
    hw = _attr(2, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [family, hw]
    con_rule = ConstraintRule(
        rule_name="scope hardware to family",
        condition_attr_id=1, condition_value="APX_NEXT",
        target_attr_id=2, allowed_values=["H1"],
    )
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], [con_rule]))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"familyAstro": "APX_NEXT", "hWVersion_astro": "H45"},
                         display_filled={"familyAstro": "APX_NEXT", "hWVersion_astro": "H45"},
                         filled_source={"familyAstro": "user", "hWVersion_astro": "auto"},
                         country="United States", status="awaiting_approval", turn=4)
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["cpq_payload"] is None, "must never emit a payload with a stale value still in it"
    assert resp["tools_called"] == ["cpq_stale_constraint_reask()"]
    assert "1. H1" in resp["answer"]
    # "H45" legitimately appears once, in the "currently H45" context note —
    # it must NOT also appear as a selectable numbered option.
    assert "H45" not in resp["answer"].split("choose one:")[-1], (
        "re-ask's option list must use the corrected, scoped set"
    )
    assert resp["session_data"]["filled"].get("hWVersion_astro") is None, (
        "stale value must be cleared, not silently kept"
    )
    assert resp["session_data"]["pending_variables"] == ["hWVersion_astro"]
    assert resp["session_data"]["status"] == "configuring"
    # The unrelated, still-valid attr must survive untouched.
    assert resp["session_data"]["filled"].get("familyAstro") == "APX_NEXT"


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — external
# review of the auto-clear fix caught 2 more gaps, pinned here.

def test_confirm_auto_clear_pushes_snapshot_before_mutating(monkeypatch):
    """The auto-clear mutation must push_snapshot first, same discipline
    as every other session mutation, so "undo" right after this re-ask
    reverts just this clear instead of skipping past it."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    family = _attr(1, "familyAstro", "Family", options=_opt("APX_NEXT", "APX_LEGACY"))
    hw = _attr(2, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [family, hw]
    con_rule = ConstraintRule(
        rule_name="scope hardware to family",
        condition_attr_id=1, condition_value="APX_NEXT",
        target_attr_id=2, allowed_values=["H1"],
    )
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], [con_rule]))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"familyAstro": "APX_NEXT", "hWVersion_astro": "H45"},
                         display_filled={"familyAstro": "APX_NEXT", "hWVersion_astro": "H45"},
                         filled_source={"familyAstro": "user", "hWVersion_astro": "auto"},
                         country="United States", status="awaiting_approval", turn=4)
    assert len(session.history) == 0
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert len(resp["session_data"]["history"]) == 1, (
        "must push a snapshot before clearing the stale value"
    )


def test_confirm_auto_clears_stale_multi_select_value_when_all_invalid(monkeypatch):
    """A multi-select attr whose ENTIRE selection is now invalid must be
    cleared from filled_multi (not silently left in place because the
    code only checked filled)."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    family = _attr(1, "familyAstro", "Family", options=_opt("APX_NEXT", "APX_LEGACY"))
    carrier = _attr(2, "carrierSel_astro", "Carrier Selection",
                     options=_opt("ATT", "VZW"), select_type="multi")
    attrs = [family, carrier]
    con_rule = ConstraintRule(
        rule_name="scope carrier to family",
        condition_attr_id=1, condition_value="APX_NEXT",
        target_attr_id=2, allowed_values=["TMO"],
    )
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], [con_rule]))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"familyAstro": "APX_NEXT"},
                         display_filled={"familyAstro": "APX_NEXT", "carrierSel_astro": "ATT, VZW"},
                         filled_multi={"carrierSel_astro": ["ATT", "VZW"]},
                         filled_source={"familyAstro": "user", "carrierSel_astro": "auto"},
                         country="United States", status="awaiting_approval", turn=4)
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["cpq_payload"] is None
    assert resp["tools_called"] == ["cpq_stale_constraint_reask()"]
    assert resp["session_data"]["filled_multi"].get("carrierSel_astro") is None, (
        "when NOTHING in the selection is still valid, the whole key must clear"
    )
    assert resp["session_data"]["pending_variables"] == ["carrierSel_astro"]


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §17 — review
# finding: clearing the ENTIRE filled_multi entry discarded every still-
# valid selection alongside the invalid one(s) — a customer with 5 valid
# carrier selections and 1 now-invalid one lost all 5.

def test_confirm_auto_clear_keeps_still_valid_multi_select_values(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    family = _attr(1, "familyAstro", "Family", options=_opt("APX_NEXT", "APX_LEGACY"))
    valid_values = ["V1", "V2", "V3", "V4", "V5"]
    carrier = _attr(
        2, "carrierSel_astro", "Carrier Selection",
        options=_opt(*valid_values, "STALE"), select_type="multi",
    )
    attrs = [family, carrier]
    con_rule = ConstraintRule(
        rule_name="scope carrier to family",
        condition_attr_id=1, condition_value="APX_NEXT",
        target_attr_id=2, allowed_values=valid_values,
    )
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], [con_rule]))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom",
        filled={"familyAstro": "APX_NEXT"},
        display_filled={"familyAstro": "APX_NEXT",
                         "carrierSel_astro": ", ".join([*valid_values, "STALE"])},
        filled_multi={"carrierSel_astro": [*valid_values, "STALE"]},
        filled_source={"familyAstro": "user", "carrierSel_astro": "auto"},
        country="United States", status="awaiting_approval", turn=4,
    )
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["cpq_payload"] is None
    assert resp["tools_called"] == ["cpq_stale_constraint_reask()"]
    assert resp["session_data"]["filled_multi"].get("carrierSel_astro") == valid_values, (
        "the 5 still-valid selections must survive — only the invalid one is cleared"
    )
    assert resp["session_data"]["pending_variables"] == ["carrierSel_astro"]
    assert "STALE" in resp["answer"], "the re-ask must name the specific invalid item"


# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §15 — review
# finding: two active constraints can legitimately intersect to an EMPTY
# allowed set (a genuine rule conflict) — auto-clearing and re-asking with
# constrained_item_values=[] produced an unanswerable "Please provide a
# value" loop, since no reply could ever match zero allowed options.

def test_confirm_reports_rule_conflict_instead_of_unanswerable_reask(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])

    family = _attr(1, "familyAstro", "Family", options=_opt("APX_NEXT", "APX_LEGACY"))
    region = _attr(2, "regionAstro", "Region", options=_opt("US", "EU"))
    hw = _attr(3, "hWVersion_astro", "Hardware Version", options=_opt("H1", "H45"))
    attrs = [family, region, hw]
    # Two rules that, both active at once, intersect to an empty allowed
    # set for hWVersion_astro — a genuine conflict, not a fixable stale value.
    con_rules = [
        ConstraintRule(
            rule_name="family scopes hw to H1",
            condition_attr_id=1, condition_value="APX_NEXT",
            target_attr_id=3, allowed_values=["H1"],
        ),
        ConstraintRule(
            rule_name="region scopes hw to H45",
            condition_attr_id=2, condition_value="EU",
            target_attr_id=3, allowed_values=["H45"],
        ),
    ]
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], con_rules))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))

    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"familyAstro": "APX_NEXT", "regionAstro": "EU",
                                 "hWVersion_astro": "H1"},
                         display_filled={"familyAstro": "APX_NEXT", "regionAstro": "EU",
                                          "hWVersion_astro": "H1"},
                         filled_source={"familyAstro": "user", "regionAstro": "user",
                                        "hWVersion_astro": "auto"},
                         country="United States", status="awaiting_approval", turn=4)
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["cpq_payload"] is None
    assert resp["tools_called"] == ["cpq_rule_conflict()"], (
        "an empty constraint intersection must be reported as a conflict, "
        "not routed into the normal auto-clear-and-reask flow"
    )
    assert "conflict" in resp["answer"].lower()
    # Nothing should be mutated — there's no productive value to clear to.
    assert resp["session_data"]["filled"].get("hWVersion_astro") == "H1"
    assert resp["session_data"]["status"] == "awaiting_approval"


# ── B2. Mid-session product/attribute change ────────────────────────────

def test_change_request_updates_filled_value_and_reruns_rule_loop(monkeypatch):
    """A plain deterministic "change X to Y" mid-configuration must update
    session.filled and leave the session ready for the next question —
    the everyday session-change path underneath every fix above."""
    _rules_setup(monkeypatch)
    housing = _attr(1, "modelSelectionHousing_astro", "Housing", options=_opt("BLACK", "GRAY"))
    attrs = [housing]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         filled={"modelSelectionHousing_astro": "BLACK"},
                         display_filled={"modelSelectionHousing_astro": "Black"},
                         status="configuring", turn=2)
    req = AskRequest(question="change housing to gray", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["session_data"]["filled"].get("modelSelectionHousing_astro") == "GRAY"


# ── B3. Q&A during active configuration ─────────────────────────────────

def test_question_mark_during_config_routes_to_qa_not_treated_as_an_answer(monkeypatch):
    _rules_setup(monkeypatch)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    attrs = [battery]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         pending_variables=["batteryType_astro"],
                         status="configuring", turn=2)
    req = AskRequest(question="what does extended battery mean?", workspace_id=1,
                      session_data=session.to_dict())
    with patch("aryx.api.ask_api._handle_cpq_qa") as mock_qa:
        mock_qa.return_value = {
            "answer": "stub qa answer", "terms": [], "tools_called": ["cpq_qa()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-qa", "answer_model": "cpq-qa"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
        resp = _run_cpq_turn(req, object())
    mock_qa.assert_called_once()
    assert resp["answer"] == "stub qa answer"
    # The pending question must not have been silently consumed as a
    # (wrong) answer attempt to batteryType_astro.
    assert "batteryType_astro" not in session.filled


# ── B4. Quote / approval submission ─────────────────────────────────────

def test_confirm_during_awaiting_approval_submits_the_payload(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    attrs = [battery]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         filled={"batteryType_astro": "STANDARD"},
                         display_filled={"batteryType_astro": "Standard"},
                         status="awaiting_approval", turn=4)
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp
    assert resp["cpq_payload"] is not None
    assert resp["session_data"]["status"] == "post_approval"
    assert resp["tools_called"] == ["cpq_payload_approved()"]


def test_confirm_is_idempotent_when_already_post_approval(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    attrs = [battery]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         filled={"batteryType_astro": "STANDARD"},
                         status="post_approval", turn=5)
    req = AskRequest(question="confirm", workspace_id=1, session_data=session.to_dict())
    resp = _run_cpq_turn(req, object())
    assert resp["cpq_payload"] is not None
    assert resp["session_data"]["status"] == "post_approval"


# ═══════════════════════════════════════════════════════════════════════
# Section C — deeper LLM-first intent coverage: multi-target dispatch,
# confidence gating, and the STEP 6 gate itself wired end-to-end through
# _run_cpq_turn (not just unit calls to _dispatch_intent_result).
# ═══════════════════════════════════════════════════════════════════════

def test_llm_first_change_requests_multi_applies_every_resolvable_target():
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    battery = _attr(2, "batteryType_astro", "Battery Type",
                     options=_opt("STANDARD", "EXTENDED"))
    attrs = [solution, battery]
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom",
        filled={"solutionTypeDevices_astro": "RadioCentral", "batteryType_astro": "STANDARD"},
        status="awaiting_approval",
    )
    req = AskRequest(question="change solution type to CloudRC and battery to extended",
                      workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_REQUESTS_MULTI, confidence=Confidence.HIGH,
        targets=[
            ChangeTarget(target_description="Solution Type", new_value_description="CloudRC"),
            ChangeTarget(target_description="Battery Type", new_value_description="EXTENDED"),
        ],
        rationale="two attrs named with values in one message",
    )
    with patch("aryx.api.ask_api._cpq_engine.build_bml_evaluator", return_value=BmlEvaluator({})):
        resp = _dispatch_intent_result(
            req, session, attrs, result, [], [], [], BmlEvaluator({}),
            classify_prompt_tokens=300, classify_completion_tokens=25,
        )
    assert resp is not None
    assert session.filled["solutionTypeDevices_astro"] == "CloudRC"
    assert session.filled["batteryType_astro"] == "EXTENDED"
    assert resp["usage"]["prompt_tokens"] == 300


def test_llm_first_change_requests_multi_falls_through_when_any_target_unresolved():
    """One resolvable target plus one that ties/fails to resolve must
    defer the WHOLE message to the deterministic path — never apply half
    a multi-attribute request while silently dropping the rest."""
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    decoy_a = _attr(2, "productInformationText_astro", "Product Information Text")
    decoy_b = _attr(3, "productSelectionProduct_all", "Product")
    attrs = [solution, decoy_a, decoy_b]
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom",
        filled={"solutionTypeDevices_astro": "RadioCentral"},
        status="awaiting_approval",
    )
    req = AskRequest(question="change solution type to CloudRC and change product too",
                      workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_REQUESTS_MULTI, confidence=Confidence.HIGH,
        targets=[
            ChangeTarget(target_description="Solution Type", new_value_description="CloudRC"),
            ChangeTarget(target_description="Product", new_value_description="something"),
        ],
        rationale="two attrs named",
    )
    resp = _dispatch_intent_result(req, session, attrs, result, [], [], [], None)
    assert resp is None
    assert session.filled["solutionTypeDevices_astro"] == "RadioCentral", (
        "must not half-apply the multi-target request"
    )


@pytest.mark.parametrize("category", [
    IntentCategory.CHANGE_REQUEST,
    IntentCategory.CHANGE_TARGET_WITHOUT_VALUE,
    IntentCategory.AMBIGUOUS,
])
def test_llm_first_low_confidence_always_falls_through_regardless_of_category(category):
    """Confidence gating is checked BEFORE category dispatch — a LOW-
    confidence classification must never drive a response, even one
    that would otherwise resolve cleanly (plan doc mitigation #9)."""
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval")
    req = AskRequest(question="change solution type", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=category, confidence=Confidence.LOW,
        target=ChangeTarget(target_description="Solution Type", new_value_description="CloudRC"),
        clarifying_question="which one?" if category == IntentCategory.AMBIGUOUS else None,
        rationale="low confidence",
    )
    resp = _dispatch_intent_result(req, session, [solution], result, [], [], [], None)
    assert resp is None


@pytest.mark.parametrize("category", [
    IntentCategory.QA_QUESTION,
    IntentCategory.APPROVAL,
    IntentCategory.ATTR_QUERY,
    IntentCategory.PRODUCT_MENTION,
    IntentCategory.RESPONSE_MODE_REQUEST,
])
def test_llm_first_uncovered_categories_defer_to_deterministic_path(category):
    """Phase 2 is explicitly PARTIAL — every category _dispatch_intent_
    result doesn't yet own must return None, not raise or guess."""
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="some message", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(category=category, confidence=Confidence.HIGH, rationale="n/a")
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is None


# ── C1. The STEP 6 gate itself, wired through the real turn — confirms
# get_settings().cpq_llm_first_enabled actually controls whether the LLM
# call happens at all, not just how _dispatch_intent_result behaves once
# a result exists. ────────────────────────────────────────────────────

def _llm_first_gate_setup(monkeypatch, *, enabled: bool):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    real_settings = api.get_settings()
    patched_settings = real_settings.model_copy(update={"cpq_llm_first_enabled": enabled})
    monkeypatch.setattr(api, "get_settings", lambda: patched_settings)


def test_llm_first_gate_calls_the_llm_and_dispatches_when_enabled(monkeypatch):
    _llm_first_gate_setup(monkeypatch, enabled=True)
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    attrs = [solution]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         display_filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval", turn=3)
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    # Real schema (GATEWAY_INTENT_JSON_SCHEMA): intent_category/confidence/
    # variable_name/value_ref/evidence_span -- the old fake_reply here used
    # a stale category/target shape from an earlier gateway contract, which
    # failed schema validation, triggered the retry-once path, and (since
    # the mock returns the same invalid reply both times) fell all the way
    # through to the deterministic detector -- masking the fact that the
    # dispatch path was never actually exercised. value_ref=1 is CloudRC,
    # the second VALUE CANDIDATES entry for solutionTypeDevices_astro.
    fake_reply = (
        '{"intent_category": "change_request", "confidence": "high", '
        '"variable_name": "solutionTypeDevices_astro", "value_ref": 1, '
        '"evidence_span": "change solution type to CloudRC", '
        '"rationale": "named attr + value"}'
    )
    # The LLM-first gateway (aryx.cpq.intent_gateway.classify_intent) calls
    # aryx.llm.complete_text directly, not llm_runtime.chat -- confirmed by
    # tracing a live call: intent_gateway.py imports `complete_text` from
    # aryx.llm and never touches llm_runtime at all, so patching
    # ask_api.llm_runtime.chat (the old target) silently mocked nothing,
    # letting a real, unmocked LLM call resolve the turn underneath the
    # test and masking the fact that the mock was never exercised.
    with patch(
        "aryx.cpq.intent_gateway.complete_text", return_value=(fake_reply, 700, 30),
    ) as mock_chat:
        resp = _run_cpq_turn(req, object())
    mock_chat.assert_called_once()
    assert resp["session_data"]["filled"]["solutionTypeDevices_astro"] == "CloudRC"
    assert resp["usage"]["prompt_tokens"] == 700
    assert resp["usage"]["menial_model"] == "cpq-llm-first"


def test_llm_first_gate_never_calls_the_llm_when_disabled(monkeypatch):
    _llm_first_gate_setup(monkeypatch, enabled=False)
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    attrs = [solution]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         display_filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval", turn=3)
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    with patch("aryx.cpq.intent_gateway.complete_text") as mock_chat:
        resp = _run_cpq_turn(req, object())
    mock_chat.assert_not_called()
    # The deterministic regex path alone must still resolve this —
    # disabling LLM-first is a routing change, not a capability loss.
    assert resp["session_data"]["filled"]["solutionTypeDevices_astro"] == "CloudRC"
    assert resp["usage"]["menial_model"] == "cpq-engine"


def test_llm_first_gate_falls_through_to_deterministic_on_unparseable_reply(monkeypatch):
    """A malformed/unparseable classification must not crash the turn —
    it logs and falls through, and the deterministic detectors still
    resolve the same message correctly."""
    _llm_first_gate_setup(monkeypatch, enabled=True)
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    attrs = [solution]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         display_filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval", turn=3)
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    with patch(
        "aryx.cpq.intent_gateway.complete_text", return_value=("not json at all", 5, 0),
    ):
        resp = _run_cpq_turn(req, object())
    assert resp["session_data"]["filled"]["solutionTypeDevices_astro"] == "CloudRC"


# ═══════════════════════════════════════════════════════════════════════
# Section D — Phase 3 QA ambiguity check (cpq_qa_ambiguity_check_enabled),
# flagged by Raven review on PR #125 as correctly implemented but
# untested. Exercises _handle_cpq_qa's graph-search branch directly, with
# every I/O boundary (graph search, term extraction, synthesis) mocked so
# only the ambiguity-check gate itself is under test.
# ═══════════════════════════════════════════════════════════════════════

def _qa_common_mocks(monkeypatch, *, ambiguity_enabled: bool):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_label_collision", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "detect_attr_query", lambda *a, **k: None)
    monkeypatch.setattr(api, "all_types", lambda *a, **k: [])
    monkeypatch.setattr(api, "_extract_terms", lambda *a, **k: ([], 10, 5, 0))
    monkeypatch.setattr(api, "gather", lambda *a, **k: ([], []))
    monkeypatch.setattr(api, "_enrich_with_attributes", lambda entities, *a, **k: entities)
    monkeypatch.setattr(api, "render_context", lambda *a, **k: "")
    real_settings = api.get_settings()
    patched_settings = real_settings.model_copy(
        update={"cpq_qa_ambiguity_check_enabled": ambiguity_enabled})
    monkeypatch.setattr(api, "get_settings", lambda: patched_settings)


def _qa_session() -> CpqSession:
    return CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")


def test_qa_ambiguity_check_asks_clarifying_question_instead_of_answering(monkeypatch):
    """A reply that reads like Q&A but the classifier flags as genuinely
    ambiguous (medium/high confidence AMBIGUOUS + a clarifying_question)
    must ask that question instead of committing to a graph-search
    answer -- and must never call _synthesise, since the ambiguity
    branch owns the response in that case."""
    _qa_common_mocks(monkeypatch, ambiguity_enabled=True)
    session = _qa_session()
    req = AskRequest(question="what about the hardware", workspace_id=1,
                      session_data=session.to_dict(), history=[])
    result = IntentResult(
        category=IntentCategory.AMBIGUOUS, confidence=Confidence.MEDIUM,
        clarifying_question="Did you mean Hardware Version or Housing?",
        rationale="both plausible",
    )
    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(result, 40, 8)), \
         patch("aryx.api.ask_api._synthesise") as mock_synth:
        resp = _handle_cpq_qa(req, session, [], object())
    mock_synth.assert_not_called()
    assert resp["answer"] == "Did you mean Hardware Version or Housing?"
    # usage sums the term-extraction call's tokens (10, 5 from the mock
    # above) with the classification call's real tokens (40, 8) -- the
    # ambiguity check runs AFTER term extraction, not instead of it.
    assert resp["usage"]["prompt_tokens"] == 50
    assert resp["usage"]["completion_tokens"] == 13


def test_qa_ambiguity_check_falls_back_to_synthesis_when_not_ambiguous(monkeypatch):
    """A genuinely non-ambiguous classification (or LOW confidence) must
    let the normal Q&A synthesis path answer, not force a clarifying
    question the classifier itself didn't actually call for."""
    _qa_common_mocks(monkeypatch, ambiguity_enabled=True)
    session = _qa_session()
    req = AskRequest(question="what does advantage service include", workspace_id=1,
                      session_data=session.to_dict(), history=[])
    result = IntentResult(category=IntentCategory.QA_QUESTION, confidence=Confidence.HIGH,
                           rationale="clear Q&A")
    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               return_value=(result, 40, 8)), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Advantage includes 24/7 support.", 20, 15, 0)) as mock_synth:
        resp = _handle_cpq_qa(req, session, [], object())
    mock_synth.assert_called_once()
    assert resp["answer"] == "Advantage includes 24/7 support."


def test_qa_ambiguity_check_never_calls_the_llm_when_disabled(monkeypatch):
    """Default-off gate: with cpq_qa_ambiguity_check_enabled=False, the
    classifier must never be invoked at all -- synthesis runs unconditionally."""
    _qa_common_mocks(monkeypatch, ambiguity_enabled=False)
    session = _qa_session()
    req = AskRequest(question="what about the hardware", workspace_id=1,
                      session_data=session.to_dict(), history=[])
    with patch("aryx.api.ask_api._llm_classify_intent_universal") as mock_classify, \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Here's what the graph shows.", 20, 15, 0)) as mock_synth:
        resp = _handle_cpq_qa(req, session, [], object())
    mock_classify.assert_not_called()
    mock_synth.assert_called_once()
    assert resp["answer"] == "Here's what the graph shows."


# docs/config_consistency_issues_2026-07-30.md issue 3 — "what are the
# Frequency Bands and Wireless Carrier available?" must answer BOTH
# attributes in one turn, not get misread as a label collision or
# silently drop one of them.

def test_handle_cpq_qa_answers_both_attrs_in_a_compound_options_query(monkeypatch):
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))

    freq = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                 options=_opt("700/800 MHz", "VHF"))
    carrier = _attr(2, "wirelessCarrier_astro", "Wireless Carrier",
                     options=_opt("ATT/FirstNet", "Verizon"))
    attrs = [freq, carrier]
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(
        question="what are the Frequency Bands and Wireless Carrier available?",
        workspace_id=1, session_data=session.to_dict(),
    )
    fake_reply = (
        '{"is_multi_attr": true, '
        '"questions": ["what are the Frequency Bands available", '
        '"what is the Wireless Carrier available"]}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        resp = _handle_cpq_qa(req, session, attrs, object())
    assert resp["tools_called"] == ["cpq_multi_attr_options()"]
    assert "Frequency Bands" in resp["answer"]
    assert "700/800 MHz" in resp["answer"]
    assert "Wireless Carrier" in resp["answer"]
    assert "ATT/FirstNet" in resp["answer"]


def test_compound_options_query_remembers_every_attribute_not_just_the_last(monkeypatch):
    """Issue 12 (docs/config_consistency_issues_2026-07-30.md): the loop
    building the compound answer above used to do `session.last_qa_variable
    = _sub_attr.variable_name` on every iteration — a single-string field
    silently overwritten each pass, so only the LAST attribute asked about
    ("Wireless Carrier") survived and "Frequency Bands" was forgotten as a
    follow-up-resolution hint. A follow-up naming BOTH attributes then had
    no conversational-recency anchor for Frequency Bands at all, making its
    resolution depend entirely on LLM classification luck. Both must now
    survive in last_qa_variables."""
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))

    freq = _attr(1, "modelSelectionFrequencyBands_astro", "Frequency Bands",
                 options=_opt("700/800 MHz", "VHF"))
    carrier = _attr(2, "wirelessCarrier_astro", "Wireless Carrier",
                     options=_opt("ATT/FirstNet", "Verizon"))
    attrs = [freq, carrier]
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(
        question="what are the Frequency Bands and Wireless Carrier available?",
        workspace_id=1, session_data=session.to_dict(),
    )
    fake_reply = (
        '{"is_multi_attr": true, '
        '"questions": ["what are the Frequency Bands available", '
        '"what is the Wireless Carrier available"]}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 10, 5)):
        _handle_cpq_qa(req, session, attrs, object())

    assert set(session.last_qa_variables) == {
        "modelSelectionFrequencyBands_astro", "wirelessCarrier_astro",
    }, (
        "a compound options query must remember EVERY attribute it asked "
        "about, not just the last one processed in the loop"
    )


def test_qa_ambiguity_check_failure_falls_back_to_synthesis_safely(monkeypatch):
    """The classifier call is wrapped in a bare except -- any failure
    (LLM error, malformed reply) must never break the Q&A turn; it must
    fall through to the normal synthesis answer."""
    _qa_common_mocks(monkeypatch, ambiguity_enabled=True)
    session = _qa_session()
    req = AskRequest(question="what about the hardware", workspace_id=1,
                      session_data=session.to_dict(), history=[])
    with patch("aryx.api.ask_api._llm_classify_intent_universal",
               side_effect=RuntimeError("llm unavailable")), \
         patch("aryx.api.ask_api._synthesise",
               return_value=("Fallback answer.", 20, 15, 0)) as mock_synth:
        resp = _handle_cpq_qa(req, session, [], object())
    mock_synth.assert_called_once()
    assert resp["answer"] == "Fallback answer."
