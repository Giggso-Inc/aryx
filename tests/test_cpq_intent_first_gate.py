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
