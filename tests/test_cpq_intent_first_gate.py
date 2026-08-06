"""Regression coverage for the intent-first gate (docs/CPQ_LLM_INTENT_FIRST_PLAN.md).

Live-traced this session (workspace 21, "how do i configure an astra
radio" -> "You said something about Svx Video Remote Speaker Microphone,
how is it connected to astra?"): STEP 1's anchor-prompting fallback
blindly swallowed a genuine question (containing "?") as the raw
product-family answer, with zero LLM/Q&A intent check, and the system
silently moved on to the next deterministic prompt instead of answering
it. These tests pin the intended, fixed behavior; they fail against the
un-patched STEP 1 fallback and must pass once the intent-first gate lands.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.api.ask_api import _run_cpq_turn, AskRequest
from aryx.cpq.state import CpqSession


def _reader():
    # _run_cpq_turn's reader param is only touched by catalog/graph lookups
    # the mocked call sites below intercept -- a bare object is enough to
    # satisfy the signature without hitting a real DB.
    return object()


def _session_awaiting_product_anchor() -> CpqSession:
    sess = CpqSession()
    sess.pending_anchor = "product"
    sess.turn = 1
    return sess


def test_question_while_pending_product_anchor_is_not_swallowed_as_anchor():
    """A message containing "?" must never become session.product_name
    verbatim, even when the system is mid-way through asking "what product
    family?" -- the exact live-confirmed bug (Amendment: intent-first gate,
    Fix 1)."""
    session = _session_awaiting_product_anchor()
    req = AskRequest(
        question="You said something about Svx Video Remote Speaker Microphone, "
                 "how is it connected to astra?",
        workspace_id=21, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.load_product_config", return_value=([], "stub")), \
         patch("aryx.api.ask_api._handle_cpq_qa") as mock_qa:
        mock_qa.return_value = {
            "answer": "stub", "terms": [], "tools_called": ["cpq_qa()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-qa", "answer_model": "cpq-qa"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
        _run_cpq_turn(req, _reader())

    # The whole point of the fix: a question-shaped message must be routed
    # to Q&A, not silently swallowed as the anchor answer.
    mock_qa.assert_called_once()


def test_plain_family_reply_still_anchors_normally():
    """A normal, non-question reply to "what product family?" (e.g.
    "aSTRO25") must NOT be diverted into the new Q&A gate -- only messages
    that actually look like questions should ever reach it."""
    session = _session_awaiting_product_anchor()
    req = AskRequest(
        question="aSTRO25_bom",
        workspace_id=21, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.load_product_config", return_value=([], "aSTRO25_bom")), \
         patch("aryx.api.ask_api._handle_cpq_qa") as mock_qa:
        _run_cpq_turn(req, _reader())

    mock_qa.assert_not_called()


# ── Regression: vague first message with exactly two ingested products ───
# Bug (found live, follow-up to the "APX" abbreviation fix): a fully
# generic first message ("I need a quote for some radios") with zero real
# product signal still produced a single, coincidental-looking "did you
# mean MOTOTRBO?" guess out of a two-product workspace — resolve_against_
# scope's own fuzzy fallback (pending_scope.py) has no sliding window for a
# candidate shorter than the query, so it fell back to a raw whole-string
# ratio between the entire sentence and each short family name, the same
# class of bug already fixed in engine.py's suggest_product_candidates.
# Fix: that secondary fallback now only runs for a short, nickname-shaped
# reply (its own documented intent); an ordinary full sentence instead
# falls through to a "did you mean A, or B?" prompt naming BOTH real
# ingested families, never a fabricated single guess.

def test_generic_first_message_with_two_products_asks_which_one_not_a_guess():
    session = CpqSession()
    req = AskRequest(
        question="I need a quote for some radios",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention", return_value=""), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.list_ingested_families",
               return_value=["APX NEXT", "MOTOTRBO"]), \
         patch("aryx.api.ask_api._cpq_engine.ingested_product_alias_map", return_value={}), \
         patch("aryx.api.ask_api._cpq_engine.suggest_product_candidates", return_value=[]), \
         patch("aryx.api.ask_api._persist_cpq_history"):
        resp = _run_cpq_turn(req, _reader())

    assert resp["tools_called"] == ["cpq_anchor_validation()"]
    assert "APX NEXT" in resp["answer"]
    assert "MOTOTRBO" in resp["answer"]


def test_generic_radio_quote_request_asks_which_product_with_three_variants():
    """"I need 10 radios quote to US" — same shape as above, but against a
    three-real-variant + one-unrelated-family workspace: must list the real
    ingested names, never invent or coincidentally guess one."""
    session = CpqSession()
    req = AskRequest(
        question="I need 10 radios quote to US",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )
    families = ["APX NEXT", "APX NEXT XE", "APX NEXT XN", "MOTOTRBO"]
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention", return_value=""), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.list_ingested_families", return_value=families), \
         patch("aryx.api.ask_api._cpq_engine.ingested_product_alias_map", return_value={}), \
         patch("aryx.api.ask_api._cpq_engine.suggest_product_candidates", return_value=[]), \
         patch("aryx.api.ask_api._persist_cpq_history"):
        resp = _run_cpq_turn(req, _reader())

    assert resp["tools_called"] == ["cpq_anchor_validation()"]
    for family in families:
        assert family in resp["answer"]


# ── Regression: an actual question about product relationships must
# route to Q&A, not be swallowed as the pending product-family answer ────
# "What other products are in the same family as the APX NEXT XE?" is a
# genuine question (ends in "?", asks about a relationship) sent while the
# engine is awaiting a product-family anchor reply — must hit the same
# intent-first gate as the original live-traced bug, not get treated as a
# (garbled) attempt to name a product.

def test_question_about_family_relationships_routes_to_qa_not_anchor():
    session = _session_awaiting_product_anchor()
    req = AskRequest(
        question="What other products are in the same family as the APX NEXT XE?",
        workspace_id=21, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.load_product_config", return_value=([], "stub")), \
         patch("aryx.api.ask_api._handle_cpq_qa") as mock_qa:
        mock_qa.return_value = {
            "answer": "stub", "terms": [], "tools_called": ["cpq_qa()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-qa", "answer_model": "cpq-qa"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
        _run_cpq_turn(req, _reader())

    mock_qa.assert_called_once()
