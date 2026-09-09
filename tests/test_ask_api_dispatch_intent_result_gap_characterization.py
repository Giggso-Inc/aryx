"""Gap-filling characterization tests for `_dispatch_intent_result`
(src/aryx/api/ask_api.py, lines 5868-6473), written ahead of the future
150-line-file refactor to pin CURRENT behavior for branches inside this
function that are not already independently exercised by
tests/test_cpq_2026_07_28_fixes.py.

This is NOT zero-coverage-from-scratch work: test_cpq_2026_07_28_fixes.py
already calls `_dispatch_intent_result` directly at ~30 call sites and
covers, among others: LOW-confidence short-circuit, AMBIGUOUS (both with
and without a clarifying_question, hidden-attr exclusion from clarify
candidates, remembered-clarify-anchor resolution), OUT_OF_SCOPE,
CHANGE_REQUEST success, CHANGE_TARGET_WITHOUT_VALUE success + unresolvable
target, CHANGE_REQUESTS_MULTI success + partial-resolution fallthrough,
MULTI_SELECT_REMOVAL (success, unselected option, invented option,
non-multi attr), ATTR_ACTIVATION (success, already-filled, required,
still-hidden), ATTR_CLEAR (success, unfilled, recommendation-would-refill),
BULK_QUANTITY_CHANGE (success, unselected grid, non-grid sibling,
non-numeric/negative/zero quantity), RESPONSE_MODE_REQUEST (json success,
batch never-dispatches, medium-confidence fallthrough), ATTR_QUERY
(high-confidence success, medium-confidence fallthrough, unresolvable
target), QA_QUESTION (high+reader success, medium fallthrough, no-reader
fallthrough), APPROVAL (success, hints threading, medium fallthrough,
rule-conflict block, dispatch for regex-unmatchable phrasing), and the
LOW-confidence-regardless-of-category parametrized gate.

The gaps this file closes (each pinned by exactly one test below):

  1. COUNTRY_CHANGE success + alias canonicalization -- NO existing test
     calls `_dispatch_intent_result` directly with this category; the only
     coverage elsewhere is end-to-end through `_run_cpq_turn_inner`
     (test_cpq_llm_first_universal_cutover_2026_08_13.py), which does not
     count as a direct pin per this task's brief.
  2. COUNTRY_CHANGE with an unrecognized country string -- characterizes
     that this branch has NO validation gate analogous to the quantity
     branches' `_is_signed_digit_quantity_text` check: any non-empty
     `country_description` is dispatched and written into session state
     verbatim when `is_recognized_country` returns None.
  3/4. DECLINE dispatch (HIGH confidence) and its Confidence.HIGH gate
     (MEDIUM falls through) -- ZERO existing test anywhere in tests/
     references `IntentCategory.DECLINE` or `_handle_decline`.
  5. PRODUCT_QUANTITY_CHANGE success path (valid positive quantity) --
     only the negative-quantity-rejection path was previously pinned.
  6. PRODUCT_QUANTITY_CHANGE with non-digit text falls through.
  7. CHANGE_REQUEST target present but `new_value_description` empty --
     the very first line inside the CHANGE_REQUEST branch was untested.
  8. CHANGE_REQUEST with a genuinely unresolvable (tied) target -- this
     exact tie fixture was used for CHANGE_TARGET_WITHOUT_VALUE/ATTR_QUERY
     but never for CHANGE_REQUEST's own target-resolution branch.
  9. ATTR_CLEAR unresolvable target (tie) falls through.
  10. ATTR_CLEAR required attr is never eligible.
  11. ATTR_CLEAR multi-select attr is never eligible.
  12. ATTR_CLEAR refuses when a constraint rule narrows the attr to
      exactly one legal value post-clear (the sibling "never a silent
      no-op" branch to the recommendation-refill one already pinned).
  13. ATTR_ACTIVATION unresolvable target (tie) falls through.
  14. ATTR_ACTIVATION already-selected-via-filled_multi is never eligible
      (only the `session.filled` half of this eligibility OR was
      previously pinned).
  15. MULTI_SELECT_REMOVAL unresolvable target (tie) falls through.
  16. BULK_QUANTITY_CHANGE unresolvable target (tie) falls through (only
      resolved-but-wrong-shape and resolved-but-unselected were pinned).
  17. CHANGE_REQUESTS_MULTI where one target resolves but the OTHER has no
      `new_value_description` at all (hits the `continue` line, distinct
      from the already-pinned "one target fails to resolve" case) --
      matches drops below 2 -> whole message falls through, no half-apply.

No pre-existing bugs were found that warranted fixing (this is a
characterize-don't-fix suite) except where explicitly noted in gap 2's
test docstring below, which documents a genuine absence of validation
rather than a crash or corruption risk.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import AskRequest
from aryx.api.ask_dispatch.ask_dispatch_intent_result import _dispatch_intent_result
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.intent_schema import ChangeTarget, Confidence, IntentCategory, IntentResult
from aryx.cpq.state import ConfigAttr, ConstraintRule, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


# ── Gap 1/2: COUNTRY_CHANGE ─────────────────────────────────────────────

def test_llm_first_country_change_dispatches_and_canonicalizes_alias(monkeypatch):
    """No product loaded (session.product_name empty), so the re-derivation
    block inside _build_country_change_response short-circuits and this
    exercises just the dispatch branch's own canonicalization step:
    `is_recognized_country` resolves a punctuation/case variant to its
    canonical common name before _build_country_change_response ever sees it."""
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    session = CpqSession(mode="cpq", product_name="", country="United States")
    req = AskRequest(question="change country to u.s.a", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.COUNTRY_CHANGE, confidence=Confidence.MEDIUM,
        country_description="u.s.a", rationale="country change",
    )
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is not None
    # Already "United States" -> canonicalization must match the existing
    # value exactly, hitting the no-op branch rather than a real change.
    assert "already set to **United States**" in resp["answer"]
    assert session.country == "United States"


def test_llm_first_country_change_applies_a_recognized_new_country(monkeypatch):
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    session = CpqSession(mode="cpq", product_name="", country="United States")
    req = AskRequest(question="change country to Germany", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.COUNTRY_CHANGE, confidence=Confidence.MEDIUM,
        country_description="Germany", rationale="country change",
    )
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is not None
    assert session.country == "Germany"
    assert "Germany" in resp["answer"]


def test_llm_first_country_change_dispatches_an_unrecognized_country_verbatim(monkeypatch):
    """Characterization, not a fix: unlike PRODUCT_QUANTITY_CHANGE/
    BULK_QUANTITY_CHANGE (both gated by `_is_signed_digit_quantity_text`
    before dispatch), the COUNTRY_CHANGE branch has NO analogous
    "is this actually a real country" gate of its own -- it only ever
    calls `_cpq_engine.is_recognized_country` to try to CANONICALIZE the
    text, falling back to the raw, unvalidated `country_description` via
    `... or result.country_description` when it isn't recognized. A
    nonsense string is therefore still dispatched and written straight
    into `session.country`, exactly as if it were a real country name.
    Whatever upstream gates exist (`validate_gateway_quarantine` etc.) are
    out of scope for this function -- this test pins THIS function's own
    behavior in isolation, matching how the file's other characterization
    tests treat "shape of the code today," not the full pipeline."""
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    session = CpqSession(mode="cpq", product_name="", country="United States")
    req = AskRequest(question="change country to Wakanda", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.COUNTRY_CHANGE, confidence=Confidence.MEDIUM,
        country_description="Wakanda", rationale="country change",
    )
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is not None
    assert session.country == "Wakanda"
    assert "Wakanda" in resp["answer"]


# ── Gap 3/4: DECLINE ─────────────────────────────────────────────────────

def test_llm_first_decline_dispatches_and_returns_to_configuring(monkeypatch):
    """ZERO prior coverage anywhere in tests/ for IntentCategory.DECLINE or
    _handle_decline -- this pins the dispatch branch added for ISSUE-002
    (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md): a real
    decline rolls the session back to "configuring" via the dedicated
    cpq_decline() tool, never cpq_payload_approved()."""
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
                         filled={"batteryType_astro": "STANDARD"}, complete=True)
    req = AskRequest(question="actually no, don't submit that", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(category=IntentCategory.DECLINE, confidence=Confidence.HIGH,
                           rationale="decline")
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is not None
    assert resp["tools_called"] == ["cpq_decline()"]
    assert resp["cpq_payload"] is None
    assert session.status == "configuring"
    assert session.complete is False


def test_llm_first_decline_medium_confidence_falls_through():
    """Same Confidence.HIGH gate as APPROVAL -- MEDIUM must defer to the
    deterministic path even though DECLINE already passed a real
    deterministic-agreement cross-check upstream (it's in
    MUTATING_CATEGORIES), per this branch's own docstring note about
    symmetry with APPROVAL."""
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="no thanks", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(category=IntentCategory.DECLINE, confidence=Confidence.MEDIUM,
                           rationale="decline")
    with patch("aryx.api.ask_json_preview_and_decline._handle_decline") as mock_decline:
        resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    mock_decline.assert_not_called()
    assert resp is None


# ── Gap 5/6: PRODUCT_QUANTITY_CHANGE ────────────────────────────────────

def test_llm_first_product_quantity_change_dispatches_a_valid_value(monkeypatch):
    """Only the negative-quantity REJECTION path was previously pinned via
    _dispatch_intent_result -- this pins the plain success path: a valid,
    in-range positive quantity is applied to session.product_quantity."""
    monkeypatch.setattr("aryx.api.ask_core_helpers._persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr("aryx.api.ask_response_building.ask_build_show_summary_response._build_show_summary_response", lambda *a, **k: None)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", product_quantity=10)
    req = AskRequest(question="change the quantity to 25", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.PRODUCT_QUANTITY_CHANGE,
        confidence=Confidence.MEDIUM, quantity_description="25", rationale="qty",
    )
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is not None
    assert resp["tools_called"] == ["cpq_product_quantity()"]
    assert session.product_quantity == 25
    assert "25" in resp["answer"]


def test_llm_first_product_quantity_change_non_digit_text_falls_through():
    """`quantity_description` that isn't signed-digit text at all (e.g. the
    LLM stated a vague amount) must fall through, mirroring
    BULK_QUANTITY_CHANGE's own non-numeric-text fallthrough."""
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", product_quantity=10)
    req = AskRequest(question="change the quantity to a bunch", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.PRODUCT_QUANTITY_CHANGE,
        confidence=Confidence.MEDIUM, quantity_description="a bunch", rationale="qty",
    )
    resp = _dispatch_intent_result(req, session, [], result, [], [], [], None)
    assert resp is None
    assert session.product_quantity == 10


# ── Gap 7/8: CHANGE_REQUEST ──────────────────────────────────────────────

def test_llm_first_change_request_without_new_value_falls_through():
    """The very first line inside the CHANGE_REQUEST branch
    (`if not result.target.new_value_description: return None`) was never
    independently exercised -- every existing CHANGE_REQUEST test supplied
    a real new_value_description."""
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom",
                         filled={"solutionTypeDevices_astro": "RadioCentral"},
                         status="awaiting_approval")
    req = AskRequest(question="change solution type", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_REQUEST, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Solution Type", new_value_description=None),
        rationale="named attr, no value",
    )
    resp = _dispatch_intent_result(req, session, [solution], result, [], [], [], None)
    assert resp is None
    assert session.filled["solutionTypeDevices_astro"] == "RadioCentral"


def test_llm_first_change_request_unresolvable_target_falls_through():
    """The tied-attr fixture (shared "Product" label) was previously used
    for CHANGE_TARGET_WITHOUT_VALUE and ATTR_QUERY, but never for
    CHANGE_REQUEST's own `_resolve_target_description` call."""
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="change product to X", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_REQUEST, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Product", new_value_description="X"),
        rationale="named attr + value",
    )
    resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    assert resp is None


# ── Gap 9-12: ATTR_CLEAR ─────────────────────────────────────────────────

def test_llm_first_attr_clear_unresolvable_target_falls_through():
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
                         filled={"productSelectionProduct_all": "A"})
    req = AskRequest(question="clear product", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_CLEAR, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Product", new_value_description=None),
        rationale="clear",
    )
    with patch("aryx.api.ask_handle.ask_handle_attr_clear._handle_attr_clear") as mock_clear:
        resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    mock_clear.assert_not_called()
    assert resp is None


def test_llm_first_attr_clear_never_clears_a_required_attr():
    """A required attr is never a valid clear target -- mirrors
    ATTR_ACTIVATION's own "required is never eligible" rule."""
    hw = _attr(1, "hWVersion_astro", "Hardware Version", required=True,
               options=_opt("H1", "H45"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
                         filled={"hWVersion_astro": "H1"})
    req = AskRequest(question="clear hardware version", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_CLEAR, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Hardware Version", new_value_description=None),
        rationale="clear",
    )
    with patch("aryx.api.ask_handle.ask_handle_attr_clear._handle_attr_clear") as mock_clear:
        resp = _dispatch_intent_result(req, session, [hw], result, [], [], [], None)
    mock_clear.assert_not_called()
    assert resp is None
    assert session.filled["hWVersion_astro"] == "H1"


def test_llm_first_attr_clear_never_clears_a_multi_select_attr():
    """MULTI_SELECT_REMOVAL owns removing individual multi-select options
    -- ATTR_CLEAR must never dispatch against a multi-select attr at all."""
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount"))
    session = CpqSession(mode="cpq", product_name="videoSolutions_BOM", status="awaiting_approval",
                         filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]})
    req = AskRequest(question="clear mounting type", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_CLEAR, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Mounting Type", new_value_description=None),
        rationale="clear",
    )
    with patch("aryx.api.ask_handle.ask_handle_attr_clear._handle_attr_clear") as mock_clear:
        resp = _dispatch_intent_result(req, session, [mount], result, [], [], [], None)
    mock_clear.assert_not_called()
    assert resp is None


def test_llm_first_attr_clear_refuses_when_a_constraint_would_narrow_to_one_option():
    """Sibling branch to the already-pinned recommendation-refill refusal:
    even with no recommendation rule firing, a live constraint that would
    narrow the post-clear options down to exactly one legal value means
    clearing would silently no-op (the customer would be right back where
    they started) -- refused, not dispatched."""
    color = _attr(1, "deviceColor_astro", "Device Color", required=False,
                   options=_opt("Black", "Silver"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
                         filled={"deviceColor_astro": "Black"})
    req = AskRequest(question="clear device color", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_CLEAR, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Device Color", new_value_description=None),
        rationale="clear",
    )
    with patch("aryx.api.ask_api._cpq_engine.apply_recommendation_rules", return_value={}), \
         patch("aryx.api.ask_api._cpq_engine.apply_constraint_rules",
               return_value={1: ["Black"]}), \
         patch("aryx.api.ask_handle.ask_handle_attr_clear._handle_attr_clear") as mock_clear:
        resp = _dispatch_intent_result(req, session, [color], result, [], [], [], None)
    mock_clear.assert_not_called()
    assert resp is None


# ── Gap 13/14: ATTR_ACTIVATION ───────────────────────────────────────────

def test_llm_first_attr_activation_unresolvable_target_falls_through():
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="add product", workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_ACTIVATION, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Product", new_value_description=None),
        rationale="activation",
    )
    with patch("aryx.api.ask_handle.ask_handle_attr_activation._handle_attr_activation") as mock_activate:
        resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    mock_activate.assert_not_called()
    assert resp is None


def test_llm_first_attr_activation_never_reactivates_an_attr_already_in_filled_multi():
    """Eligibility check tests BOTH `session.filled` and
    `session.filled_multi.get(...)` via an `or` -- only the `filled` half
    was previously pinned; this pins the `filled_multi` half."""
    mount = _attr(1, "mountingTypeArray_viSoln", "Mounting Type", select_type="multi",
                  options=_opt("Shirt Magnetic Mount", "Jacket Magnetic Mount"))
    session = CpqSession(mode="cpq", product_name="videoSolutions_BOM", status="awaiting_approval",
                         filled_multi={"mountingTypeArray_viSoln": ["Shirt Magnetic Mount"]})
    req = AskRequest(question="add mounting type", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.ATTR_ACTIVATION, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Mounting Type", new_value_description=None),
        rationale="activation",
    )
    with patch("aryx.api.ask_handle.ask_handle_attr_activation._handle_attr_activation") as mock_activate:
        resp = _dispatch_intent_result(req, session, [mount], result, [], [], [], None)
    mock_activate.assert_not_called()
    assert resp is None


# ── Gap 15: MULTI_SELECT_REMOVAL ─────────────────────────────────────────

def test_llm_first_multi_select_removal_unresolvable_target_falls_through():
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval",
                         filled_multi={"productSelectionProduct_all": ["A"]})
    req = AskRequest(question="remove A from product", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.MULTI_SELECT_REMOVAL, confidence=Confidence.HIGH,
        target=ChangeTarget(target_description="Product", new_value_description="A"),
        rationale="removal",
    )
    with patch("aryx.api.ask_handle.ask_handle_multi_select_removal._handle_multi_select_removal") as mock_remove:
        resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    mock_remove.assert_not_called()
    assert resp is None


# ── Gap 16: BULK_QUANTITY_CHANGE ─────────────────────────────────────────

def test_llm_first_bulk_quantity_change_unresolvable_target_falls_through():
    a = _attr(1, "productInformationText_astro", "Product Information Text")
    b = _attr(2, "productSelectionProduct_all", "Product")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", status="awaiting_approval")
    req = AskRequest(question="change product quantity to 67", workspace_id=1,
                      session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.BULK_QUANTITY_CHANGE, confidence=Confidence.MEDIUM,
        target=ChangeTarget(target_description="Product"),
        quantity_description="67", rationale="bulk qty",
    )
    resp = _dispatch_intent_result(req, session, [a, b], result, [], [], [], None)
    assert resp is None


# ── Gap 17: CHANGE_REQUESTS_MULTI ────────────────────────────────────────

def test_llm_first_change_requests_multi_skips_a_target_with_no_new_value():
    """Distinct from the already-pinned "one target fails to RESOLVE" case:
    here BOTH targets resolve to real attrs, but the second carries no
    `new_value_description` at all, hitting the `if not t.new_value_
    description: continue` line rather than the resolution-failure path.
    Either way matches drops below 2, so the whole message must still
    fall through with no half-apply."""
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
    req = AskRequest(question="change solution type to CloudRC and mention battery",
                      workspace_id=1, session_data=session.to_dict())
    result = IntentResult(
        category=IntentCategory.CHANGE_REQUESTS_MULTI, confidence=Confidence.HIGH,
        targets=[
            ChangeTarget(target_description="Solution Type", new_value_description="CloudRC"),
            ChangeTarget(target_description="Battery Type", new_value_description=None),
        ],
        rationale="second target named but no value given",
    )
    resp = _dispatch_intent_result(req, session, attrs, result, [], [], [], None)
    assert resp is None
    assert session.filled["solutionTypeDevices_astro"] == "RadioCentral", (
        "must not half-apply even though the first target alone would "
        "have resolved cleanly"
    )
    assert session.filled["batteryType_astro"] == "STANDARD"
