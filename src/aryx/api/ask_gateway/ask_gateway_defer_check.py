"""Deciding whether to defer the LLM-first gateway to the deterministic
pending-answer path, split out of `_llm_first_gateway_turn` (Phase 7/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md) purely to keep the sibling `ask_handle_llm_first_gateway_turn.py`
under the line cap. Logic unchanged from the original inline block.
`_cpq_engine` is read through the ask_api MODULE object (not imported by
name) since at least one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_llm.ask_llm_topic_switch_and_change_decline import _pending_reply_is_topic_switch
from aryx.api.ask_llm.ask_llm_usage_and_new_request_detect import _pending_reply_looks_like_new_request

_BARE_REPLY_MAX_WORDS = 6


def _should_defer_gateway_to_pending_answer(
    req: "Any", session: Any, attrs: list,
) -> bool:
    """2026-08-18 fix: a bare reply that verbatim (or near-verbatim)
    matches one of the PENDING attr's own real menu options is answering
    that question -- never send it to the LLM gateway for fresh
    classification first. Confirmed live: a customer picking
    "SmartLocate" from a pending promoApplicationServices_astro multi-
    select had no change-verb, so `_pending_reply_is_topic_switch`'s
    deterministic check correctly said "not a topic switch" -- but with
    nothing ELSE checked, the gateway still ran and the LLM
    reinterpreted the bare item name as a change-intent against an
    unrelated attribute, inventing a "which value for SmartLocate?"
    follow-up with no basis in real catalog structure (no such per-item
    attr exists). Reuses `apply_answer`'s own already-trusted matcher
    (exact item_value/display-name, numeric selection, substring/word-
    boundary) -- no new matching logic.

    PR #212 review (M1) -- corrected: `apply_answer` matches against the
    FULL, unrestricted reply text via substring/word-boundary branches
    with no length cap, so a genuine topic switch that happens to
    mention the pending attr's own option name as a whole word (e.g.
    pending=Country, reply="since it ships to Canada, change the
    hardware version instead") would ALSO satisfy this match -- the
    original `matches_own_options or not topic_switch` let that false
    positive override a correct topic-switch verdict.

    Fixed two ways, since the deterministic topic-switch regex
    (`_pending_reply_looks_like_new_request`) alone doesn't reliably
    catch every compound-sentence phrasing:
      1. A word-count cap -- a BARE reply answering the pending
         question is short by construction; a genuine topic switch is a
         real sentence. This is the primary, robust guard.
      2. The cheap deterministic check still runs and wins outright
         when it DOES catch a switch, as defense in depth -- never
         consult apply_answer at all once it says "new request."

    PR #212 review follow-up: the word-count cap above exists to stop
    apply_answer's substring/word-boundary branches from false-
    positiving on a topic switch that happens to NAME the pending
    attr's option as one word in a longer sentence -- but it also
    blocked a genuine bare reply that IS a real catalog option whose
    own name is long (e.g. "APX NEXT XE 4G LTE PLUS 5G", 7 words, a
    real item_value/display_name in this same catalog family). An
    EXACT item_value/display-name match can't produce that false
    positive regardless of length -- it only fires when the reply, as
    a whole, equals one specific real option verbatim -- so it bypasses
    the cap entirely, while substring/fuzzy matches still respect it.
    """
    from aryx.api import ask_api as _ask_api_module
    _pending_attr_for_gate = None
    if session.pending_variables and session.turn > 1:
        _pending_attr_for_gate = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
    _looks_like_new_request = bool(
        _pending_attr_for_gate is not None
        and _pending_reply_looks_like_new_request(
            req.question, _pending_attr_for_gate, attrs,
            session.filled, session.filled_multi,
        )
    )
    _reply_norm = req.question.strip().lower()
    _exact_option_match = bool(
        not _looks_like_new_request
        and _pending_attr_for_gate is not None
        and any(
            _reply_norm in (o.item_value.strip().lower(), o.display_name.strip().lower())
            for o in (_pending_attr_for_gate.options or [])
        )
    )
    _pending_reply_matches_own_options = bool(
        not _looks_like_new_request
        and _pending_attr_for_gate is not None
        and _pending_attr_for_gate.options
        and (
            _exact_option_match
            or len(req.question.split()) <= _BARE_REPLY_MAX_WORDS
        )
        and _ask_api_module._cpq_engine.apply_answer(_pending_attr_for_gate, req.question)
    )
    if _pending_attr_for_gate is None:
        return False
    if _looks_like_new_request:
        return False
    if _pending_reply_matches_own_options:
        return True
    return not _pending_reply_is_topic_switch(
        req.question, _pending_attr_for_gate, attrs,
        session.filled, session.filled_multi, req.workspace_id,
    )
