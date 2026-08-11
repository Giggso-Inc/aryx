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
         patch("aryx.api.ask_api._cpq_engine.list_ingested_families", return_value=["aSTRO25_bom"]), \
         patch("aryx.api.ask_api._persist_cpq_history"), \
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


# ── Regression: a session poisoned by an earlier WRONG "did you mean"
# suggestion must not stay trapped repeating it forever ──────────────────
# Live-traced (screenshots): "Give me quote of APX with 10 qty" got the
# wrong "did you mean videoSolutions_BOM?" reply, which set
# session.pending_scope_candidates = ["videoSolutions_BOM"]. The user's
# VERY NEXT message — "Give me quote of APXNEXT with 10 qty", a full,
# unambiguous product name — got the SAME wrong "did you mean
# videoSolutions_BOM?" reply again, even though that exact question
# resolved correctly in a brand-new session. Root cause: the PROMPT 7
# "reply to a prior did-you-mean list" block always ran
# resolve_against_scope() against the STALE candidate list FIRST, and its
# own "miss"-tier suggestion short-circuited the return before
# detect_product_mention() ever ran fresh on the new text. Fix: a
# confident fresh detection now wins over a weak/stale scope match.

def test_confident_new_mention_escapes_a_session_poisoned_by_a_prior_wrong_suggestion():
    session = CpqSession()
    session.pending_anchor = "product"
    session.pending_scope_kind = "product_suggestions"
    session.pending_scope_candidates = ["videoSolutions_BOM"]
    session.turn = 1
    req = AskRequest(
        question="Give me quote of APXNEXT with 10 qty",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention",
               return_value="APX NEXT"), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.load_product_config",
               return_value=([], "APX NEXT")), \
         patch("aryx.api.ask_api._persist_cpq_history"):
        resp = _run_cpq_turn(req, _reader())

    assert resp["tools_called"] != ["cpq_product_did_you_mean()"], (
        "must not repeat the stale wrong suggestion once a confident, "
        "different detection is available on the new message"
    )
    assert resp["session_data"]["product_name"] == "APX NEXT"


def test_stale_scope_reask_still_fires_when_the_new_message_also_has_no_signal():
    """The escape hatch above must not swallow the legitimate case: if the
    new message ALSO fails to resolve to anything, the stale-scope reask
    must still fire (never silently drop the pending disambiguation)."""
    session = CpqSession()
    session.pending_anchor = "product"
    session.pending_scope_kind = "product_suggestions"
    session.pending_scope_candidates = ["videoSolutions_BOM"]
    session.turn = 1
    req = AskRequest(
        question="xyz totally unrelated gibberish",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention", return_value=""), \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._persist_cpq_history"):
        resp = _run_cpq_turn(req, _reader())

    assert resp["tools_called"] == ["cpq_product_did_you_mean()"]
    assert "videoSolutions_BOM" in resp["answer"]


# ── Regression (Raven review M1): the escape-hatch detection must not
# double-fetch the ingested product catalog ───────────────────────────────
# When the stale-scope check's own fresh detect_product_mention() call ALSO
# finds nothing AND resolve_against_scope's suggestions come back empty (a
# real, if narrow, path — e.g. a stale candidate list that normalizes to
# nothing), execution used to fall through to the pre-existing
# "if not detected:" block below and call detect_product_mention() again
# with IDENTICAL arguments — the exact "loaded the same inventory twice
# through graph+RDB queries" cost detect_product_mention's own docstring
# already documents as a previously-fixed finding. _fresh_detection_tried
# now guards that second call once the first one already ran.

def test_escape_hatch_detection_is_not_fetched_twice_on_the_double_miss_path():
    session = CpqSession()
    session.pending_anchor = "product"
    session.pending_scope_kind = "product_suggestions"
    # Normalizes to "" in resolve_against_scope, so its own fuzzy ladder
    # produces matched=None, suggestions=[] — the exact path that used to
    # fall through to a second, redundant detect_product_mention() call.
    session.pending_scope_candidates = ["---"]
    session.turn = 1
    req = AskRequest(
        question="xyz totally unrelated gibberish",
        workspace_id=1, history=[], session_data=session.to_dict(),
    )
    with patch("aryx.api.ask_api._cpq_engine.detect_product_mention",
               return_value="") as mock_detect, \
         patch("aryx.api.ask_api._cpq_engine.resolve_product_hint", return_value=None), \
         patch("aryx.api.ask_api._cpq_engine.list_ingested_families", return_value=[]), \
         patch("aryx.api.ask_api._persist_cpq_history"):
        _run_cpq_turn(req, _reader())

    assert mock_detect.call_count == 1, (
        "detect_product_mention must be called at most once per turn on "
        "the double-miss path, not re-fetched with identical arguments"
    )
