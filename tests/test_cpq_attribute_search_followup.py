"""Attribute-first discovery, phase 4: replies to the bot's attribute questions.

- After "Which one do you need?" (label only), the reply is matched against
  the values on offer and continues like a first message naming that value.
- After a numbered family choice, step 1 picks the family and fills in the
  value remembered for it.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_api import AskRequest, run_ask
from aryx.api.ask_attribute_followup import _route_attribute_followup
from aryx.cpq.attribute_search.lookup import AttributeSearchResult
from aryx.cpq.state import CpqSession

_F = "aryx.api.ask_attribute_followup"
_ORIGIN = "Which products are available for carrier selection"


@pytest.fixture(autouse=True)
def _stubs():
    with patch("aryx.api.ask_api._cpq_engine", MagicMock()), \
         patch("aryx.api.ask_core_helpers._persist_cpq_history"):
        yield


def _waiting_session(**extra) -> dict:
    s = CpqSession()
    s.pending_attribute_label = "carrier selection"
    s.product_anchor_question = _ORIGIN
    for k, v in extra.items():
        setattr(s, k, v)
    return s.to_dict()


def _req(reply: str, **extra) -> AskRequest:
    return AskRequest(question=reply, workspace_id=704, history=[],
                      session_data=_waiting_session(**extra))


_OFFERED = AttributeSearchResult(
    phrase="carrier selection", labels=["Carrier Selection"], value=None,
    offered_values=["ATT/FirstNet (provided by Motorola)",
                    "Verizon Priority & Preemption (provided by Motorola)"],
)
_FOUND = AttributeSearchResult(phrase="carrier selection", labels=["Carrier Selection"],
                               value="ATT/FirstNet (provided by Motorola)", products=[{"model": "x"}])


def test_reply_is_matched_to_an_offered_value_and_continues():
    with patch(f"{_F}.find_products_by_attribute", side_effect=[_OFFERED, _FOUND]) as find, \
         patch(f"{_F}.decide", return_value={"answer": "started"}) as decide:
        out = _route_attribute_followup(_req("ATT"), object())
    assert out == {"answer": "started"}
    assert find.call_args_list[1].args[:2] == (
        "carrier selection", "ATT/FirstNet (provided by Motorola)")
    meta = decide.call_args.args[2]
    assert (meta.attribute_label, meta.attribute_value) == (
        "carrier selection", "ATT/FirstNet (provided by Motorola)")
    assert decide.call_args.kwargs["anchor_question"] == _ORIGIN


def test_numbered_reply_picks_that_value():
    with patch(f"{_F}.find_products_by_attribute", side_effect=[_OFFERED, _FOUND]) as find, \
         patch(f"{_F}.decide", return_value={"answer": "ok"}):
        _route_attribute_followup(_req("2"), object())
    assert find.call_args_list[1].args[1].startswith("Verizon")


def test_quantity_and_country_on_the_session_are_carried():
    with patch(f"{_F}.find_products_by_attribute", side_effect=[_OFFERED, _FOUND]), \
         patch(f"{_F}.decide", return_value={}) as decide:
        _route_attribute_followup(_req("ATT", product_quantity=5, country="Germany"), object())
    meta = decide.call_args.args[2]
    assert (meta.quantity, meta.country) == (5, "Germany")


def test_reply_that_is_not_a_value_returns_none():
    with patch(f"{_F}.find_products_by_attribute", return_value=_OFFERED), \
         patch(f"{_F}.decide") as decide:
        assert _route_attribute_followup(_req("actually I want APX Next"), object()) is None
    decide.assert_not_called()


def test_lookup_error_returns_none():
    with patch(f"{_F}.find_products_by_attribute", side_effect=RuntimeError("db")):
        assert _route_attribute_followup(_req("ATT"), object()) is None


# ── run_ask hook ─────────────────────────────────────────────────────────────


def _run_ask(req, followup_result):
    cfg = MagicMock(cpq_intent_mode="llm_first", cpq_intent_timeout_s=5.0)
    with patch("aryx.api.ask_api.get_settings", return_value=cfg), \
         patch("aryx.api.ask_core_helpers._reader", return_value=MagicMock()), \
         patch("aryx.api.ask_attribute_followup._route_attribute_followup",
               return_value=followup_result) as followup, \
         patch("aryx.api.ask_api.hard_off_topic", return_value=True), \
         patch("aryx.api.ask_standard_pipeline._standard_ask_pipeline",
               return_value={"answer": "normal"}) as normal:
        out = run_ask(req)
    return out, followup, normal


def test_run_ask_sends_a_pending_reply_to_the_followup():
    out, followup, normal = _run_ask(_req("ATT"), {"answer": "followed up"})
    assert out == {"answer": "followed up"}
    followup.assert_called_once()
    normal.assert_not_called()


def test_run_ask_forgets_the_question_when_the_reply_is_not_a_value():
    out, _, normal = _run_ask(_req("tell me a joke"), None)
    assert out == {"answer": "normal"}
    assert normal.call_args.args[0].session_data["pending_attribute_label"] == ""


def test_run_ask_skips_the_followup_when_nothing_is_pending():
    req = AskRequest(question="hello", workspace_id=1, history=[], session_data={})
    _, followup, _ = _run_ask(req, None)
    followup.assert_not_called()


# ── step 1: picking an offered family fills in its value ─────────────────────


def test_step1_fills_in_the_value_for_the_family_the_customer_picks():
    from aryx.api.ask_turn_steps import ask_step1_product_anchor as step1

    session = CpqSession()
    session.pending_anchor = "product"
    session.pending_scope_kind = "product_suggestions"
    session.pending_scope_candidates = ["aSTRO25_bom", "MOTOTRBO"]
    session.attribute_search_seeds = {
        "aSTRO25_bom": [{"vn": "wirelessCarrier", "item_value": "ATT/FIRSTNET",
                         "display": "ATT/FirstNet", "select_type": "single"}],
        "MOTOTRBO": [{"vn": "carrierM", "item_value": "ATT", "display": "ATT",
                      "select_type": "single"}],
    }
    engine = MagicMock()
    engine.detect_qa_question.return_value = False
    req = SimpleNamespace(question="1", workspace_id=704)
    with patch("aryx.api.ask_api._cpq_engine", engine), \
         patch.object(step1, "_resolve_scope_reply",
                      return_value=SimpleNamespace(matched="aSTRO25_bom")):
        assert step1._step1_resolve_product_anchor(req, session, object(), {}) is None
    assert session.product_name == "aSTRO25_bom"
    assert session.filled == {"wirelessCarrier": "ATT/FIRSTNET"}
    assert session.filled_source == {"wirelessCarrier": "hint"}
    assert session.attribute_search_seeds == {}
