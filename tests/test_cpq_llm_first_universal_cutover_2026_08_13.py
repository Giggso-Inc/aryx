"""Phase 4 — universal LLM-first cutover (docs/CPQ_LLM_INTENT_FIRST_
UNIVERSAL_PLAN.md §8): the LLM-first dispatcher (_dispatch_intent_result,
via the shared _llm_first_gateway_turn) previously only ran inside the
awaiting_approval/post_approval status branch -- it never fired during
the actual configuring-stage conversation, which is most real traffic.

These tests prove:
- cpq_llm_first_universal_enabled=False (default) leaves configuring-
  stage turns exactly as before -- the gateway is never even consulted
  when the message has no deterministic trigger at all.
- cpq_llm_first_universal_enabled=True makes the SAME dispatcher run
  during configuring-stage turns too, via the shared function -- no
  double dispatch (single call site discipline).
- The two new dispatch branches added this session (PRODUCT_QUANTITY_
  CHANGE, COUNTRY_CHANGE) resolve correctly through the dispatcher.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import AskRequest, _run_cpq_turn_inner
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


def _setup(monkeypatch, *, universal_enabled: bool, llm_first_enabled: bool = True):
    # `top_level_route_used()` is a contextvars.ContextVar with no
    # autouse reset fixture in this suite -- in synchronous pytest
    # execution (no real async context boundary between tests), a prior
    # test's `mark_top_level_route_used()` call can leak into a later
    # test run in the same thread, making the "N4: skip when top-level
    # already ran this turn" gate wrongly short-circuit. Reset explicitly
    # per test rather than relying on suite-wide ordering.
    from aryx.cpq.intent_gateway import _top_level_route_used
    _token = _top_level_route_used.set(False)
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "resolve_always_ask_skips", lambda *a, **k: set())
    monkeypatch.setattr(api._cpq_engine, "build_bml_evaluator", lambda *a, **k: BmlEvaluator({}))
    monkeypatch.setattr(api._cpq_engine, "load_hiding_rules", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "load_recommendation_and_constraint_rules",
                         lambda *a, **k: ([], []))
    monkeypatch.setattr(api._cpq_engine, "load_validation_rules", lambda *a, **k: [])
    real_settings = api.get_settings()
    patched_settings = real_settings.model_copy(update={
        "cpq_llm_first_enabled": llm_first_enabled,
        "cpq_llm_first_universal_enabled": universal_enabled,
    })
    monkeypatch.setattr(api, "get_settings", lambda: patched_settings)


def _confirming_decision(category, *, variable_name=None, quantity_text=None, country_text=None):
    return GatewayDecision(
        action="dispatch",
        result=GatewayIntentResult(
            intent_category=category, confidence=Confidence.HIGH,
            variable_name=variable_name, quantity_text=quantity_text,
            country_text=country_text, evidence_span="", rationale="test-confirm",
        ),
    )


def test_universal_flag_off_never_consults_the_gateway_during_configuring(monkeypatch):
    """Default (off): a configuring-stage turn with no deterministic
    trigger at all must never even call the gateway -- proves the new
    call site is a true no-op when the flag is off."""
    _setup(monkeypatch, universal_enabled=False)
    mounts = _attr(1, "mountType_astro", "Mount Type",
                    options=_opt("Shirt Mount", "Jacket Mount"), select_type="multi")
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([mounts], "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         status="configuring", turn=2)
    req = AskRequest(question="hello there, just checking in", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "gateway_classify_intent") as mock_gw:
        _run_cpq_turn_inner(req, object())
    mock_gw.assert_not_called()


def test_universal_flag_on_dispatches_multi_select_removal_during_configuring(monkeypatch):
    """Enabled: the SAME dispatcher that only used to run post-approval
    now resolves a real mutating action during the actual configuring
    conversation -- the core Phase 4 regression."""
    _setup(monkeypatch, universal_enabled=True)
    mounts = _attr(1, "mountType_astro", "Mount Type",
                    options=_opt("Shirt Mount", "Jacket Mount"), select_type="multi")
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([mounts], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        status="configuring", turn=2,
        filled_multi={"mountType_astro": ["Shirt Mount", "Jacket Mount"]},
    )
    req = AskRequest(question="remove Jacket Mount", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(
            IntentCategory.MULTI_SELECT_REMOVAL, variable_name="mountType_astro",
        ),
    ) as mock_gw, patch.object(api, "_handle_multi_select_removal") as mock_handle:
        mock_handle.return_value = {
            "answer": "removed", "terms": [], "tools_called": [],
            "usage": {}, "grounding": None,
            "session_data": session.to_dict(), "cpq_payload": None,
        }
        _run_cpq_turn_inner(req, object())
    # Single call site discipline: exactly one gateway consult for the
    # whole turn -- the deterministic gate's own confirm-checkpoint must
    # never ALSO run once the universal dispatcher already resolved it.
    mock_gw.assert_called_once()
    mock_handle.assert_called_once()


def test_universal_flag_on_still_skipped_for_awaiting_approval_status(monkeypatch):
    """The universal call site must defer to the existing awaiting_
    approval/post_approval call site rather than double-classifying --
    proven by the gateway being consulted exactly once even though both
    call sites exist in the same turn."""
    _setup(monkeypatch, universal_enabled=True)
    solution = _attr(1, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([solution], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        filled={"solutionTypeDevices_astro": "RadioCentral"},
        display_filled={"solutionTypeDevices_astro": "RadioCentral"},
        status="awaiting_approval", turn=3,
    )
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(
            IntentCategory.CHANGE_REQUEST, variable_name="solutionTypeDevices_astro",
        ),
    ) as mock_gw:
        resp = _run_cpq_turn_inner(req, object())
    mock_gw.assert_called_once()
    assert resp["session_data"]["filled"]["solutionTypeDevices_astro"] == "CloudRC"


def test_product_quantity_change_dispatches_through_the_universal_gateway(monkeypatch):
    _setup(monkeypatch, universal_enabled=True)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         status="configuring", turn=2, product_quantity=1)
    req = AskRequest(question="please change the overall quantity to 25", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(
            IntentCategory.PRODUCT_QUANTITY_CHANGE, quantity_text="25",
        ),
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["product_quantity"] == 25


def test_country_change_dispatches_through_the_universal_gateway(monkeypatch):
    _setup(monkeypatch, universal_enabled=True)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="United States",
                         status="configuring", turn=2)
    req = AskRequest(question="please change the country to Canada", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(
            IntentCategory.COUNTRY_CHANGE, country_text="Canada",
        ),
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["country"] == "Canada"


def test_bare_reply_matching_pending_multiselect_option_skips_the_gateway(monkeypatch):
    """Live bug: a customer picking "SmartLocate" from a pending
    promoApplicationServices_astro-shaped multi-select was sent to the
    LLM gateway for fresh classification (no change-verb, so the
    deterministic topic-switch check said "not a switch" but nothing
    else short-circuited the gateway) -- the LLM then reinterpreted the
    bare item name as a change-intent against an unrelated attribute.
    A bare reply that verbatim matches one of the PENDING attr's own
    real menu options must never reach the gateway at all."""
    _setup(monkeypatch, universal_enabled=True)
    promo = _attr(
        1, "promoApplicationServices_astro", "Promo Application Services",
        options=_opt("SmartProgramming", "SmartConnect", "SmartLocate",
                     "SmartMapping", "SmartMessaging", "ViQi Virtual Partner"),
        select_type="multi", required=False,
    )
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([promo], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        status="configuring", turn=3,
        pending_variables=["promoApplicationServices_astro"],
    )
    req = AskRequest(question="SmartLocate", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(api, "gateway_classify_intent") as mock_gw:
        _run_cpq_turn_inner(req, object())
    mock_gw.assert_not_called()


def test_change_verb_topic_switch_during_pending_multiselect_still_uses_gateway(monkeypatch):
    """Sibling regression guard: the fix only short-circuits BARE menu-
    option replies. A genuine "change X to Y" topic switch during the
    same pending multi-select must still reach the gateway unchanged --
    the change-verb phrasing never matches the pending attr's own
    options, so `apply_answer` returns None and the existing
    topic-switch path still runs."""
    _setup(monkeypatch, universal_enabled=True)
    promo = _attr(
        1, "promoApplicationServices_astro", "Promo Application Services",
        options=_opt("SmartProgramming", "SmartConnect", "SmartLocate"),
        select_type="multi", required=False,
    )
    solution = _attr(2, "solutionTypeDevices_astro", "Solution Type",
                      options=_opt("RadioCentral", "CloudRC"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([promo, solution], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        status="configuring", turn=3,
        pending_variables=["promoApplicationServices_astro"],
        filled={"solutionTypeDevices_astro": "RadioCentral"},
        display_filled={"solutionTypeDevices_astro": "RadioCentral"},
    )
    req = AskRequest(question="change solution type to CloudRC", workspace_id=1,
                      session_data=session.to_dict())
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(
            IntentCategory.CHANGE_REQUEST, variable_name="solutionTypeDevices_astro",
        ),
    ) as mock_gw:
        _run_cpq_turn_inner(req, object())
    # A pre-existing, unrelated double-dispatch quirk affects some
    # CHANGE_REQUEST-category flows in this harness (reproduces
    # identically without Issue A's fix applied at all) -- this test only
    # needs to prove the gateway is NOT skipped for a genuine topic
    # switch, not pin the exact call count that quirk affects.
    assert mock_gw.called, "a genuine change-verb topic switch must still reach the gateway"


def test_topic_switch_mentioning_pending_options_own_value_still_uses_gateway(monkeypatch):
    """PR #212 review (M1): apply_answer's substring/word-boundary
    branches have no length cap on the reply text -- a genuine topic
    switch that happens to mention the PENDING attr's own option name as
    a whole word (here: pending=Country, option "Canada", reply switches
    to Hardware Version but names "Canada" along the way) must not be
    misfiled as "answering the pending question." This exact wording was
    verified to NOT trip the cheap deterministic change-verb regex
    (`_pending_reply_looks_like_new_request`) either, so the word-count
    cap on the bare-reply shortcut is the guard actually being tested
    here -- it must fall through to the real (LLM-backed) topic-switch
    check rather than short-circuiting on the word-boundary match."""
    _setup(monkeypatch, universal_enabled=True)
    country_attr = _attr(
        1, "ultimateDestinationCountry", "Ultimate Destination Country",
        options=_opt("United States", "Canada", "Mexico"),
    )
    hw_attr = _attr(2, "hWVersion_astro", "Hardware Version",
                     options=_opt("4G LTE+5G", "4G LTE Only"))
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([country_attr, hw_attr], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        status="configuring", turn=3,
        pending_variables=["ultimateDestinationCountry"],
    )
    req = AskRequest(
        question="since it ships to Canada, change the hardware version instead",
        workspace_id=1, session_data=session.to_dict(),
    )
    with patch.object(
        api, "_llm_detect_pending_topic_switch", return_value="hWVersion_astro",
    ), patch.object(
        api, "gateway_classify_intent",
        return_value=_confirming_decision(
            IntentCategory.CHANGE_REQUEST, variable_name="hWVersion_astro",
        ),
    ) as mock_gw:
        _run_cpq_turn_inner(req, object())
    assert mock_gw.called, (
        "a genuine change-verb topic switch must reach the gateway even "
        "when it mentions the pending attr's own option name in passing"
    )


def test_long_verbatim_option_name_bare_reply_bypasses_the_word_count_cap(monkeypatch):
    """PR #212 review follow-up: the word-count cap on the bare-reply
    shortcut exists so apply_answer's substring/word-boundary branches
    can't false-positive on a topic switch that merely NAMES the
    pending attr's option inside a longer sentence -- but a reply that
    IS, verbatim, a real catalog option whose own name is long (7 words
    here) is not that failure mode at all: an EXACT item_value/display-
    name match can only fire when the whole reply equals one specific
    real option, regardless of length. This must still be treated as
    answering the pending question, not routed to the (LLM-backed)
    topic-switch classifier."""
    _setup(monkeypatch, universal_enabled=True)
    product_attr = _attr(
        1, "productSelectionProduct_all", "Product",
        options=_opt("APX NEXT XE 4G LTE PLUS 5G", "APX NEXT ENHANCED"),
    )
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([product_attr], "aSTRO25_bom"))
    session = CpqSession(
        mode="cpq", product_name="aSTRO25_bom", country="United States",
        status="configuring", turn=3,
        pending_variables=["productSelectionProduct_all"],
    )
    req = AskRequest(
        question="APX NEXT XE 4G LTE PLUS 5G",
        workspace_id=1, session_data=session.to_dict(),
    )
    with patch.object(
        api, "_llm_detect_pending_topic_switch", return_value=None,
    ), patch.object(api, "gateway_classify_intent") as mock_gw:
        _run_cpq_turn_inner(req, object())
    assert not mock_gw.called, (
        "a verbatim, exact catalog option name must be treated as "
        "answering the pending question regardless of its word count, "
        "never routed to the gateway/LLM topic-switch classifier"
    )
