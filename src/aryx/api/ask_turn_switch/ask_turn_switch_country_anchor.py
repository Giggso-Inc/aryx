"""Handling a reply to the "switch_country" pending anchor (a prior turn
found the carried-over country invalid for the new product and asked for
a different one), split out of `_run_cpq_turn_inner` (Phase 10/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
purely to keep the sibling `ask_turn_product_switch_anchor.py` under the
line cap. Logic unchanged from the original inline `if` block. `logger`
and `_persist_cpq_history` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_turn_country_available_for import _country_available_for
from aryx.api.ask_turn_switch.ask_turn_product_switch_complete import _complete_product_switch
from aryx.raven_log import raven_log


def _handle_switch_country_anchor(
    req: "Any", session: Any, reader: Any,
) -> dict[str, Any] | None:
    """A prior turn found the carried-over country invalid for the new
    product and asked for a different one — this turn's text is that
    attempt (same "bare reply" convention as the normal country anchor:
    try the NL-hint extractor first, else the raw trimmed text —
    CPQ_CASCADE_CONVERSATION_PLAN.md D1).

    Decline path first (Issue 10, docs/CPQ_PRODUCT_SWITCH_ISSUE.md): this
    state previously had NO way out — every reply was treated as a
    country attempt, and worse, a decline-shaped reply ("no") could
    silently COMPLETE the switch with a garbage country, since an
    unmatchable country fills nothing, no constraint fires, and the
    availability check fails open by design. EXACT-phrase match only —
    confirm_switch's startswith(("n","no")) convention would swallow real
    countries here (Norway, Netherlands, Nigeria, North Macedonia all
    start with "n").

    Returns None when the switch completes successfully — the caller
    falls through to STEP 1, which sees session.country/product_name
    already set and proceeds straight to STEP 2 for the new catalog.
    """
    from aryx.api import ask_api as _ask_api_module
    _sc_reply = req.question.strip().lower()
    if _sc_reply in ("n", "no", "cancel", "stop", "abort",
                     "never mind", "nevermind"):
        session.pending_switch_product = ""
        session.pending_switch_question = ""
        session.pending_anchor = ""
        _ask_api_module.logger.info(
            "cpq_switch: switch_country declined turn=%s staying on product=%r",
            session.turn, session.product_name,
        )
        raven_log("INFO", "P4", "ask.switch.country_declined switch abandoned at country re-ask", context={
            "selected_option": "decline",
            "available_options": ["decline", "complete_switch", "reask_country"],
            "reason_code": "EXACT_DECLINE_PHRASE", "turn": getattr(session, "turn", None),
            "current_product": getattr(session, "product_name", "") or "",
            "reply_len": len(_sc_reply)})
        answer = f"OK — continuing with **{session.product_name}**."
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_switch_declined()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    # docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md: always the raw
    # reply, never `hints.get("country")` -- the customer was just
    # asked to name the replacement country, so (like the normal
    # country anchor above) their entire message IS the answer; the
    # old `hints.get("country") or ...` fallback let a regex
    # misparse of THIS SAME reply (e.g. "in CANADA" -> "Ca") win
    # over the correct raw text purely because a truthy-but-wrong
    # match short-circuited the `or`.
    new_country = req.question.strip()
    new_product = session.pending_switch_product
    if _country_available_for(reader, req.workspace_id, new_product, new_country):
        raven_log("DEBUG", "P4", "ask.switch.country_accepted replacement country valid, completing switch",
                  context={
                      "selected_option": "complete_switch",
                      "available_options": ["decline", "complete_switch", "reask_country"],
                      "reason_code": "COUNTRY_AVAILABLE", "new_product": new_product,
                      "country_len": len(new_country), "turn": getattr(session, "turn", None)})
        _complete_product_switch(session, new_product, new_country)
        # Fall through — Step 1 below sees session.country already set
        # and session.product_name already the new product, so it
        # proceeds straight to Step 2 for the new catalog.
        return None
    _ask_api_module.logger.info(
        "cpq_switch: country=%r still invalid for pending_product=%r turn=%s",
        new_country, new_product, session.turn,
    )
    raven_log("INFO", "P4", "ask.switch.country_reask replacement country still invalid, asking again", context={
        "selected_option": "reask_country",
        "available_options": ["decline", "complete_switch", "reask_country"],
        "reason_code": "COUNTRY_NOT_AVAILABLE_FOR_NEW_PRODUCT", "new_product": new_product,
        "country_len": len(new_country), "turn": getattr(session, "turn", None)})
    answer = (
        f"**{new_product}** isn't available for **{new_country}** either. "
        f"Could you provide a different country to continue switching?"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_switch_country_invalid()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
