"""Building a switch-confirmation or ambiguous-switch-suggestion prompt
once a message on an already-anchored session was determined NOT to be
an answer to the pending attribute, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_turn_switch_
redetect.py` under the line cap. Logic unchanged from the original
inline block. `_cpq_engine`, `logger`, and `_persist_cpq_history` are
read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.cpq.pending_scope.pending_scope import set_pending_scope


def _build_switch_redetect_prompt(
    req: "Any", session: Any, reader: Any, hints: dict,
    alias_map: dict[str, str] | None, switch_candidate: str | None,
) -> dict[str, Any] | None:
    """Alias inventory fetched ONCE for this turn, and only on the
    non-answer path (review finding P2 — plus the answer guard already
    skips the fetch entirely for ordinary answers). Reuses the probe
    from the answer-guard step when it already computed alias_map/
    switch_candidate — no need to hit the graph twice.

    Returns a response dict when this turn's reply was consumed by a
    switch-confirmation or ambiguous-switch prompt; None when no
    confident or plausible switch candidate was found at all, in which
    case the caller continues with the rest of the turn unchanged.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if alias_map is None:
        alias_map = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
        switch_candidate = _cpq_engine.detect_product_mention(
            req.question, hints, reader, req.workspace_id,
            alias_map=alias_map,
        )
    if switch_candidate and switch_candidate.strip().lower() != session.product_name.strip().lower():
        _ask_api_module.logger.info(
            "cpq_switch: candidate detected turn=%s current=%r candidate=%r",
            session.turn, session.product_name, switch_candidate,
        )
        session.pending_switch_product = switch_candidate
        session.pending_switch_question = req.question
        session.pending_anchor = "confirm_switch"
        answer = (
            f"It looks like you're asking about **{switch_candidate}**, but this "
            f"session is configuring **{session.product_name}**. Switch to "
            f"**{switch_candidate}** and discard the current configuration? (yes/no)"
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_switch_candidate()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # No confident switch candidate — but the message might still be a
    # garbled/partial attempt at naming a product (fuzzy score in the
    # "maybe" band, below confirm-worthy but above pure noise). Rather
    # than silently ignore it, offer up to 5 real candidates so the
    # client isn't left unrecognised with no signal anything was
    # ambiguous.
    suggestions = _cpq_engine.suggest_product_candidates(
        req.question, reader, req.workspace_id, exclude=session.product_name,
        alias_map=alias_map,
    )
    if not suggestions:
        return None
    _ask_api_module.logger.info(
        "cpq_switch: ambiguous product mention turn=%s current=%r suggestions=%r",
        session.turn, session.product_name, suggestions,
    )
    # The hint question MUST set a pending state its reply can be
    # matched against (Issue 7): the stateless version of this prompt
    # let a "yes" reply fall through to the approval handler, which
    # SUBMITTED the current quote the user was trying to switch away
    # from (confirmed live). One candidate → the existing confirm_switch
    # gate handles yes/no (and its country re-validation); several →
    # suggest_switch, whose gate re-prompts on a bare "yes" instead of
    # guessing. PROMPT 7: also set pending_scope so a near-miss typo on
    # the reply re-asks within these suggestions only.
    set_pending_scope(
        session,
        kind="product_suggestions",
        candidates=list(suggestions),
        origin_question=req.question,
        attr_vn="",
        asked_turn=session.turn,
    )
    if len(suggestions) == 1:
        session.pending_switch_product = suggestions[0]
        session.pending_switch_question = req.question
        session.pending_anchor = "confirm_switch"
        answer = (
            f"I couldn't tell if that's a different product — did you "
            f"mean **{suggestions[0]}**? Switching would discard the "
            f"current **{session.product_name}** configuration. (yes/no)"
        )
    else:
        session.pending_switch_candidates = suggestions
        session.pending_anchor = "suggest_switch"
        sug_list = ", ".join(f"**{s}**" for s in suggestions)
        answer = (
            f"I couldn't tell if that's a different product — did you "
            f"mean one of: {sug_list}? Reply with the product name, or "
            f"say **no** to continue with **{session.product_name}**."
        )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_switch_ambiguous()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
