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
    _resolve_target_description,
    _run_cpq_turn,
    _with_classify_usage,
)
from aryx.cpq.bml import BmlEvaluator, evaluate_tier1
from aryx.cpq.engine import CpqEngine
from aryx.cpq.intent_schema import ChangeTarget, Confidence, IntentCategory, IntentResult
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


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
    fake_reply = (
        '{"category": "change_request", "confidence": "high", '
        '"target": {"target_description": "Solution Type", '
        '"new_value_description": "CloudRC"}, "rationale": "named attr + value"}'
    )
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=(fake_reply, 700, 30)) as mock_chat:
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
    with patch("aryx.api.ask_api.llm_runtime.chat") as mock_chat:
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
    with patch("aryx.api.ask_api.llm_runtime.chat", return_value=("not json at all", 5, 0)):
        resp = _run_cpq_turn(req, object())
    assert resp["session_data"]["filled"]["solutionTypeDevices_astro"] == "CloudRC"
