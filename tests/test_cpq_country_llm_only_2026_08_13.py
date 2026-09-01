"""Regression coverage for docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md --
owner directive: "I don't need regex to decide country at any point, llm
should do that." Covers the C-series QA sheet defects that are turn-1
shaped or explicit-change-command shaped, the new
`_llm_confirm_and_extract_country` checkpoint, the dropped "Country-once"
regex re-scan, the switch-country raw-reply fix, and the new explicit
LLM-call-failure message.
"""
from __future__ import annotations

from unittest.mock import patch

import aryx.api.ask_api as api
from aryx.api.ask_api import (
    AskRequest,
    Turn,
    _llm_confirm_and_extract_country,
    _mine_history_for_cpq_context,
    _run_cpq_turn_inner,
)
from aryx.cpq.engine import CpqEngine
from aryx.cpq.intent_gateway import AskRouteDecision, GatewayDecision
from aryx.cpq.intent_schema import (
    Confidence,
    GatewayIntentResult,
    IntentCategory,
    validate_gateway_quarantine,
)
from aryx.cpq.state import CpqSession


def _country_decision(category, country_text=None):
    return GatewayDecision(
        action="dispatch",
        result=GatewayIntentResult(
            intent_category=category, confidence=Confidence.HIGH,
            country_text=country_text, evidence_span="", rationale="test",
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# _llm_confirm_and_extract_country -- the new checkpoint, in isolation
# ═══════════════════════════════════════════════════════════════════════

def _base_req_session():
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="anything", workspace_id=1, session_data=session.to_dict())
    return req, session


def test_extract_returns_the_llms_own_country():
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_country_decision(IntentCategory.COUNTRY_CHANGE, "Canada"),
    ):
        confirmed, country, call_failed = _llm_confirm_and_extract_country(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="",
        )
    assert (confirmed, country, call_failed) == (True, "Canada", False)


def test_extract_rejects_on_category_disagreement():
    """A real, successful classification into a DIFFERENT category is a
    disagreement, not a failure -- call_failed must stay False so the
    caller falls through to normal processing, not the explicit
    "classifier call failed" message (review finding, 2026-08-13)."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_country_decision(IntentCategory.AMBIGUOUS),
    ):
        confirmed, country, call_failed = _llm_confirm_and_extract_country(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="",
        )
    assert (confirmed, country, call_failed) == (False, None, False)


def test_extract_rejects_on_gateway_exception():
    """An exception from the gateway call itself IS a failure -- must
    surface call_failed=True so the caller shows the explicit
    "classifier call failed" message (review finding, 2026-08-13: this
    used to be indistinguishable from a normal disagreement)."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent", side_effect=TimeoutError("llm unreachable"),
    ):
        confirmed, country, call_failed = _llm_confirm_and_extract_country(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="",
        )
    assert (confirmed, country, call_failed) == (False, None, True)


def test_extract_reports_call_failed_on_a_reason_based_timeout():
    """Same failure signal as the exception path, but via a `fallback`
    decision with reason="timeout" -- classify_intent's own reject-on-
    failure path (never raises TimeoutError itself, per its docstring),
    so call_failed detection can't rely on catching an exception alone."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=GatewayDecision(action="fallback", result=None, reason="timeout"),
    ):
        confirmed, country, call_failed = _llm_confirm_and_extract_country(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="",
        )
    assert (confirmed, country, call_failed) == (False, None, True)


def test_extract_rejects_an_unrecognized_country_defensively():
    """Quarantine should already prevent this, but the checkpoint itself
    never trusts an unrecognized country_text either -- belt and
    suspenders, no regex fallback. Not a call failure either -- the call
    succeeded, it just didn't produce anything usable."""
    req, session = _base_req_session()
    with patch.object(
        api, "gateway_classify_intent",
        return_value=_country_decision(IntentCategory.COUNTRY_CHANGE, "Wakanda"),
    ):
        confirmed, country, call_failed = _llm_confirm_and_extract_country(
            req, session, [], hiding_rules=[], rec_rules=[], con_rules=[],
            bml_eval=None, catalog_prefix="",
        )
    assert (confirmed, country, call_failed) == (False, None, False)


# ═══════════════════════════════════════════════════════════════════════
# Explicit change command -- value comes from country_text, never the
# regex's own capture group (C14/C15 real-pipeline behavior + the new
# "no regex decides the value" invariant)
# ═══════════════════════════════════════════════════════════════════════

def test_change_command_value_is_the_llms_country_not_the_regex_capture(monkeypatch):
    """The regex (_COUNTRY_CHANGE_RE) would capture "Canada" correctly
    here too, but the LLM's country_text is deliberately mocked to a
    DIFFERENT value -- proving the value comes from the LLM call, not
    from `_country_change_match`."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    monkeypatch.setattr(
        api, "gateway_classify_intent",
        lambda *a, **k: _country_decision(IntentCategory.COUNTRY_CHANGE, "Germany"),
    )
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(question="change country to Canada", workspace_id=1,
                      session_data=session.to_dict())
    resp = _run_cpq_turn_inner(req, object())
    assert resp["session_data"]["country"] == "Germany"


# ═══════════════════════════════════════════════════════════════════════
# Turn-1: route_meta.country authoritative, zero regex involvement
# ═══════════════════════════════════════════════════════════════════════

def test_turn1_llm_country_wins_with_no_preposition_at_all(monkeypatch):
    """C48: "Generate a quote: ..., United States" has no preposition
    before the country at all -- _COUNTRY_PREP structurally cannot match
    this. route_meta.country (a full-sentence LLM read) has no such
    requirement."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="Generate a quote: APX NEXT XN All Band, Qty 1, United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=1, country="United States",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["country"] == "United States"


def test_turn1_llm_country_wins_over_definite_article_regex_gap(monkeypatch):
    """C30: "in the United States" -- the definite article breaks
    _COUNTRY_PREP's capture start entirely. route_meta.country has no
    such fragility."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="What is the pricing for APX models in the United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=None, country="United States",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["country"] == "United States"


def test_turn1_llm_country_wins_over_allcaps_word_boundary_regex_bug(monkeypatch):
    """C40: "in CANADA" -- _COUNTRY_PREP's [A-Z]{2} branch has no
    trailing word boundary and grabs only "CA" -> "Ca", which
    is_recognized_country then rejects. route_meta.country supplies the
    real value instead."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "list_ingested_families", lambda *a, **k: [])
    monkeypatch.setattr(api._cpq_engine, "resolve_product_hint", lambda *a, **k: None)
    session = CpqSession(mode="cpq")
    req = AskRequest(
        question="I want a quote for APX NEXT in CANADA",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=None, country="Canada",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"]["country"] == "Canada"


# ═══════════════════════════════════════════════════════════════════════
# Explicit LLM-call-failure message (owner directive: "LLM failure
# should return LLM failed try again later", never silently fall back
# to a regex guess or a generic re-ask)
# ═══════════════════════════════════════════════════════════════════════

def test_router_timeout_surfaces_an_explicit_failure_message_not_a_generic_reask(monkeypatch):
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    # A product is already selected -- otherwise the turn short-circuits
    # on the earlier "need a product family" gate before ever reaching
    # the country-determination logic under test here.
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(
        question="Give me a quote for APX NEXT in United States",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="low", clarifying_question=None,
        rationale="timeout", timed_out=True, error="timeout",
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["session_data"].get("country") in (None, "")
    assert resp["tools_called"] == ["cpq_llm_call_failed()"]
    assert "try again" in resp["answer"].lower()


def test_mid_conversation_gateway_timeout_also_surfaces_the_explicit_failure_message(
    monkeypatch,
):
    """Review finding, 2026-08-13: a mid-conversation "change country to
    X" command whose gateway call times out used to be indistinguishable
    from a normal disagreement (both collapsed to confirmed=False), so it
    silently fell through to the generic hint/attribute re-ask instead of
    the explicit "classifier call failed" message turn-1 already
    guarantees. Must now surface the same explicit message here too."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom", country="Canada")
    req = AskRequest(
        question="please change my country to Germany", workspace_id=1,
        session_data=session.to_dict(),
    )
    with patch.object(
        api, "gateway_classify_intent",
        return_value=GatewayDecision(action="fallback", result=None, reason="timeout"),
    ):
        resp = _run_cpq_turn_inner(req, object())
    assert resp["tools_called"] == ["cpq_llm_call_failed()"]
    assert "try again" in resp["answer"].lower()
    # The old country must never be silently discarded or changed on a
    # call failure -- it simply wasn't touched this turn.
    assert resp["session_data"]["country"] == "Canada"


def test_turn1_no_country_stated_at_all_still_asks_normally(monkeypatch):
    """Distinguishes "the LLM call failed" from "the LLM succeeded and
    correctly found no country" -- the latter must still ask normally,
    not claim a failure that didn't happen."""
    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    monkeypatch.setattr(api._cpq_engine, "load_product_config",
                         lambda *a, **k: ([], "aSTRO25_bom"))
    session = CpqSession(mode="cpq", product_name="aSTRO25_bom")
    req = AskRequest(
        question="Start a new order for APX NEXT XE All Band",
        workspace_id=1, session_data=session.to_dict(),
    )
    route_meta = AskRouteDecision(
        route="quote", confidence="high", clarifying_question=None,
        rationale="ok", quantity=None, country=None,
    )
    resp = _run_cpq_turn_inner(req, object(), route_meta)
    assert resp["tools_called"] == ["cpq_anchor_validation()"]
    assert "destination country" in resp["answer"]


# ═══════════════════════════════════════════════════════════════════════
# _mine_history_for_cpq_context -- the 6th regex-decided-value site the
# original PR audit missed (review finding, 2026-08-13). No LLM call to
# route through here (it recovers a country from an earlier, non-CPQ
# turn), so this is fallback-path regex hardening, not an LLM fix --
# the same discipline as the mechanical quantity-cluster fixes.
# ═══════════════════════════════════════════════════════════════════════

def test_mine_history_recovers_country_despite_a_definite_article():
    """"...in the United States" used to fail _COUNTRY_PREP outright --
    the customer's country would have been silently lost when CPQ starts
    on a later turn after an earlier standard-Ask turn stated it this
    way."""
    session = CpqSession(mode="cpq")
    history = [
        Turn(role="user", text="I need pricing for APX Next in the United States"),
        Turn(role="assistant", text="Sure, here are some options..."),
    ]
    _mine_history_for_cpq_context(session, history, CpqEngine())
    assert session.country == "United States"


def test_mine_history_not_shadowed_by_an_earlier_bogus_allcaps_match():
    """A bogus earlier trigger ("for APX Next" truncating to a fragment)
    must never shadow a real, later-stated country in the same
    historical message -- the leftmost-match-wins failure mode this
    review finding also cited."""
    session = CpqSession(mode="cpq")
    history = [
        Turn(role="user", text="What is the pricing for APX models in the United States"),
    ]
    _mine_history_for_cpq_context(session, history, CpqEngine())
    assert session.country == "United States"


def test_mine_history_never_latches_a_bogus_product_fragment_as_a_country():
    """Regression guard: a message with NO real country stated must
    never latch a product-name fragment ("Apx"/"Apx Next") as if it
    were one."""
    session = CpqSession(mode="cpq")
    history = [
        Turn(role="user", text="Start a new order for APX NEXT XE All Band"),
    ]
    _mine_history_for_cpq_context(session, history, CpqEngine())
    assert not session.country


# ═══════════════════════════════════════════════════════════════════════
# Quarantine structural safety for a malformed COUNTRY_CHANGE result
# (review finding, 2026-08-13). The concern raised: nothing structurally
# stops the LLM from populating variable_name/value_ref instead of
# country_text for this no-target category (the exact shape of the
# "deliver to Canada" bug the country_text schema-description fix
# closed). These tests confirm `validate_gateway_quarantine` already
# fails CLOSED (downgrades to AMBIGUOUS) for this shape regardless of
# what variable_name holds -- country_text being missing/unrecognized is
# the ONE thing this quarantine actually requires for COUNTRY_CHANGE, so
# a malformed result can never silently reach `_llm_confirm_and_extract_
# country`'s caller as if it were a real, usable country.
# ═══════════════════════════════════════════════════════════════════════

def test_quarantine_rejects_country_change_missing_country_text_even_with_a_real_variable_name():
    """The LLM populated a REAL, injected catalog attribute's variable_
    name instead of country_text -- exactly what a schema mix-up like the
    live "deliver to Canada" bug looked like before the country_text
    description was strengthened. Must still downgrade to AMBIGUOUS: a
    real variable_name doesn't make a no-target category's missing value
    field acceptable."""
    result = GatewayIntentResult(
        intent_category=IntentCategory.COUNTRY_CHANGE,
        confidence=Confidence.HIGH,
        variable_name="ultimateDestinationCountry_astro",
        country_text=None,
        evidence_span="", rationale="test",
    )
    out = validate_gateway_quarantine(
        result, "deliver to Canada",
        candidate_vns={"ultimateDestinationCountry_astro"}, value_counts={},
    )
    assert out.intent_category == IntentCategory.AMBIGUOUS


def test_quarantine_rejects_country_change_with_variable_name_and_unrecognized_country_text():
    """Even when country_text IS populated, an unrecognized value must
    still reject -- a real variable_name alongside it doesn't lower the
    bar."""
    result = GatewayIntentResult(
        intent_category=IntentCategory.COUNTRY_CHANGE,
        confidence=Confidence.HIGH,
        variable_name="ultimateDestinationCountry_astro",
        country_text="Wakanda",
        evidence_span="", rationale="test",
    )
    out = validate_gateway_quarantine(
        result, "deliver to Wakanda",
        candidate_vns={"ultimateDestinationCountry_astro"}, value_counts={},
    )
    assert out.intent_category == IntentCategory.AMBIGUOUS
