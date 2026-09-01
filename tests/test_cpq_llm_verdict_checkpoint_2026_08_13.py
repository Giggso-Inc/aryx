"""Regression coverage for the "blanket LLM-as-final-verdict" checkpoint —
follow-up to docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md.

Live bug this closes: "Change country to United States unless the
quantity is 6. If it is 6, do nothing." was misread as a command to set
quantity=6 -- a global change-verb regex ("change") and a quantity-value
regex ("quantity is 6") each matched independently, compounding across a
conditional clause neither one understands. The country instruction was
never processed at all.

Fix: 5 deterministic gates (PRODUCT_QUANTITY_CHANGE, CHANGE_REQUEST,
MULTI_SELECT_REMOVAL, ATTR_ACTIVATION, ATTR_CLEAR) now require the SAME
existing LLM intent gateway (gateway_classify_intent) to independently
agree before acting -- reject-on-failure: any exception, disagreement, or
None result means the deterministic match is NOT trusted, and the turn
falls through to normal processing instead.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _llm_confirm_deterministic_intent, _run_cpq_turn_inner
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.intent_gateway import GatewayDecision
from aryx.cpq.intent_schema import Confidence, GatewayIntentResult, IntentCategory
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _opt(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values)]


def _attr(eid, vn, label, *, options=None, required=False, select_type="single") -> ConfigAttr:
    return ConfigAttr(
        entity_id=eid, variable_name=vn, display_label=label, required=required,
        default_value="", options=options or [], select_type=select_type,
    )


def _confirming_decision(category: IntentCategory, variable_name: str | None = None):
    return GatewayDecision(
        action="dispatch",
        result=GatewayIntentResult(
            intent_category=category, confidence=Confidence.HIGH,
            variable_name=variable_name, quantity_text="1" if variable_name is None else None,
            evidence_span="", rationale="test-confirm",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# _llm_confirm_deterministic_intent — the shared checkpoint, in isolation
# ═══════════════════════════════════════════════════════════════════════

def _base_req_session():
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="anything", workspace_id=1, session_data=session.to_dict())
    return req, session


def test_confirm_returns_true_when_gateway_agrees_on_category():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.PRODUCT_QUANTITY_CHANGE),
    ):
        assert _llm_confirm_deterministic_intent(
            req, session, [], IntentCategory.PRODUCT_QUANTITY_CHANGE,
            [], [], [], None, "",
        ) is True


def test_confirm_returns_false_when_gateway_disagrees_on_category():
    """The exact mechanism of the reported bug: the deterministic gate
    assumed PRODUCT_QUANTITY_CHANGE, but the LLM classifies the message
    as something else entirely (or ambiguous) -- reject, don't act."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.AMBIGUOUS),
    ):
        assert _llm_confirm_deterministic_intent(
            req, session, [], IntentCategory.PRODUCT_QUANTITY_CHANGE,
            [], [], [], None, "",
        ) is False


def test_confirm_returns_false_when_variable_name_mismatches():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.CHANGE_REQUEST, "wrongAttr_astro"),
    ):
        assert _llm_confirm_deterministic_intent(
            req, session, [], IntentCategory.CHANGE_REQUEST,
            [], [], [], None, "", expected_variable_name="batteryType_astro",
        ) is False


def test_confirm_returns_false_when_gateway_result_is_none():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=GatewayDecision(action="fallback", result=None),
    ):
        assert _llm_confirm_deterministic_intent(
            req, session, [], IntentCategory.PRODUCT_QUANTITY_CHANGE,
            [], [], [], None, "",
        ) is False


def test_confirm_rejects_on_any_exception_never_trusts_the_deterministic_match():
    """Reject-on-failure, deliberately: an LLM outage must never silently
    fall back to trusting the regex -- that's exactly what produced the
    live bug this checkpoint exists to close."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent", side_effect=TimeoutError("llm unreachable"),
    ):
        assert _llm_confirm_deterministic_intent(
            req, session, [], IntentCategory.PRODUCT_QUANTITY_CHANGE,
            [], [], [], None, "",
        ) is False


# ═══════════════════════════════════════════════════════════════════════
# The exact reported bug — full turn, quantity gate
# ═══════════════════════════════════════════════════════════════════════

def test_conditional_sentence_naming_an_unrelated_quantity_is_not_misread_as_a_command(
    monkeypatch,
):
    """"Change country to United States unless the quantity is 6. If it
    is 6, do nothing." -- the exact live transcript. Regex alone would
    misread this as "set quantity to 6" (a global change-verb match on
    "Change" + a quantity-value match on "quantity is 6", compounding
    across a conditional clause neither regex understands). The gateway
    correctly classifies this as NOT a quantity-change command, so the
    deterministic match must be rejected -- quantity stays unchanged and
    the turn falls through instead of answering "Quantity → 6"."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: GatewayDecision(
            action="clarify",
            result=GatewayIntentResult(
                intent_category=IntentCategory.AMBIGUOUS, confidence=Confidence.LOW,
                evidence_span="", clarifying_question="Did you mean to change the country?",
                rationale="conditional clause, not a quantity command",
            ),
        ),
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"batteryType_astro": "STANDARD"}, product_quantity=1,
    )
    req = AskRequest(
        question="Change country to United States unless the quantity is 6. "
                  "If it is 6, do nothing.",
        workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["product_quantity"] == 1
    assert resp.get("tools_called") not in (
        ["cpq_product_quantity()"], ["cpq_product_quantity_rejected()"],
    )
    assert "Quantity → 6" not in resp.get("answer", "")


def test_genuine_quantity_command_still_works_when_gateway_confirms(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: GatewayDecision(
            action="dispatch",
            result=GatewayIntentResult(
                intent_category=IntentCategory.PRODUCT_QUANTITY_CHANGE,
                confidence=Confidence.HIGH, quantity_text="6",
                evidence_span="", rationale="test-confirm",
            ),
        ),
    )
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        pending_variables=["batteryType_astro"], status="configuring",
        product_quantity=1,
    )
    req = AskRequest(question="change the quantity to 6", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["product_quantity"] == 6
    assert resp["tools_called"] == ["cpq_product_quantity()"]


# ═══════════════════════════════════════════════════════════════════════
# The other 4 gates — checkpoint wiring proven via the shared handler
# ═══════════════════════════════════════════════════════════════════════

def test_multi_select_removal_confirmed_by_gateway_executes(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    # The pre-existing "LLM-first mid-session gateway" call (ask_api.py,
    # gated on cpq_llm_first_enabled/top_level_route_used) runs BEFORE
    # STEP 6 and would consume this test's globally-mocked
    # gateway_classify_intent first, dispatching through its own mapping
    # instead of ever reaching the STEP 6 checkpoint under test here.
    monkeypatch.setattr(api, "top_level_route_used", lambda: True)
    mounts = _attr(1, "mountType_astro", "Mount Type",
                    options=_opt("Shirt Mount", "Jacket Mount"), select_type="multi")
    attrs = [mounts]
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: (attrs, "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        status="awaiting_approval",
        filled_multi={"mountType_astro": ["Shirt Mount", "Jacket Mount"]},
    )
    req = AskRequest(question="remove Jacket Mount", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.MULTI_SELECT_REMOVAL, "mountType_astro"),
    ), patch.object(api, "_handle_multi_select_removal") as mock_handle:
        mock_handle.return_value = {"answer": "removed", "terms": [], "tools_called": [],
                                     "usage": {}, "grounding": None,
                                     "session_data": session.to_dict(), "cpq_payload": None}
        _run_cpq_turn_inner(req, object())
    mock_handle.assert_called_once()


def test_multi_select_removal_rejected_by_gateway_never_executes(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    mounts = _attr(1, "mountType_astro", "Mount Type",
                    options=_opt("Shirt Mount", "Jacket Mount"), select_type="multi")
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([mounts], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled_multi={"mountType_astro": ["Shirt Mount", "Jacket Mount"]},
    )
    req = AskRequest(question="remove Jacket Mount", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.AMBIGUOUS),
    ), patch.object(api, "_handle_multi_select_removal") as mock_handle:
        _run_cpq_turn_inner(req, object())
    mock_handle.assert_not_called()


def test_attr_activation_rejected_by_gateway_never_executes(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    warranty = _attr(2, "extendedWarranty_astro", "Extended Warranty",
                      options=_opt("Yes"), required=False)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([warranty], "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="add extended warranty", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api._cpq_engine, "detect_attr_activation", return_value=warranty,
    ), patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.AMBIGUOUS),
    ), patch.object(api, "_handle_attr_activation") as mock_handle:
        _run_cpq_turn_inner(req, object())
    mock_handle.assert_not_called()


def test_attr_clear_rejected_by_gateway_never_executes(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States", filled={"batteryType_astro": "STANDARD"},
    )
    req = AskRequest(question="clear battery type", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api._cpq_engine, "detect_attr_clear", return_value=battery,
    ), patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.AMBIGUOUS),
    ), patch.object(api, "_handle_attr_clear") as mock_handle:
        _run_cpq_turn_inner(req, object())
    mock_handle.assert_not_called()


def test_change_request_rejected_by_gateway_never_executes(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    battery = _attr(1, "batteryType_astro", "Battery Type", options=_opt("STANDARD", "EXTENDED"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([battery], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States", filled={"batteryType_astro": "STANDARD"},
    )
    req = AskRequest(question="change battery type to extended", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api._cpq_engine, "detect_change_request", return_value=(battery, "EXTENDED"),
    ), patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(IntentCategory.AMBIGUOUS),
    ), patch.object(api, "_handle_cascade") as mock_handle:
        _run_cpq_turn_inner(req, object())
    mock_handle.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# COUNTRY_CHANGE — session-level country field, same follow-up
# (docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md): "change country
# to X" had NO deterministic detector at all before this, so it fell
# through to generic attribute-disambiguation instead of ever being
# recognized as a country-change request.
# ═══════════════════════════════════════════════════════════════════════

def _confirm_country_change(monkeypatch, country: str = "United States") -> None:
    """docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md: the country-change
    gate now extracts the VALUE from this same call's `country_text`,
    never from the deterministic regex's own capture -- the mock must
    supply a real `country_text` matching what the test expects, exactly
    like quantity_text had to for the quantity-checkpoint tests."""
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: GatewayDecision(
            action="dispatch",
            result=GatewayIntentResult(
                intent_category=IntentCategory.COUNTRY_CHANGE, confidence=Confidence.HIGH,
                country_text=country, evidence_span="", rationale="test-confirm",
            ),
        ),
    )


def test_live_bug_repro_country_command_is_recognized_and_quantity_is_not(monkeypatch):
    """Exact reported live bug (with quantity=10 in the actual transcript):
    the country instruction must be processed, and the conditional
    "unless the quantity is 10" clause must NOT be misread as a command
    to set the quantity."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    _confirm_country_change(monkeypatch)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", product_quantity=1)
    req = AskRequest(
        question=(
            "Change country to United States unless the quantity is 10. "
            "If it is 10, do nothing."
        ),
        workspace_id=1, session_data=session.to_dict(),
    )
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["country"] == "United States"
    assert resp["session_data"]["product_quantity"] == 1


def test_country_change_confirmed_by_gateway_updates_session(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    _confirm_country_change(monkeypatch, country="Canada")
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="please change my country to Canada", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["country"] == "Canada"
    assert resp["tools_called"] == ["cpq_country_change()"]


def test_country_change_already_matching_current_value_is_a_no_op_message(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    _confirm_country_change(monkeypatch)
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States")
    req = AskRequest(question="change country to United States", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["country"] == "United States"
    assert "already set" in resp["answer"]


def test_country_change_rejected_by_gateway_never_updates_session(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: _confirming_decision(IntentCategory.AMBIGUOUS),
    )
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="Canada")
    req = AskRequest(question="change country to United States", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp.get("tools_called") != ["cpq_country_change()"]
