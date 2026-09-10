"""Handling a reply to the "confirm_switch" pending anchor (a prior turn
offered a single candidate product to switch to), split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline `elif` block; the decline sub-path lives in the sibling
`ask_turn_confirm_switch_decline.py` purely to keep this file under the
line cap. `logger` and `_llm_classify_switch_reply` are read through the
ask_api MODULE object (not imported by name) since ask_api tests patch
several of its own module-level names by dotted path.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.api.ask_llm.ask_llm_switch_reply_and_compound_split import _llm_classify_switch_reply
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_turn_switch.ask_turn_confirm_switch_decline import _handle_confirm_switch_decline
from aryx.api.ask_turn_country_available_for import _country_available_for
from aryx.api.ask_turn_switch.ask_turn_product_switch_complete import _complete_product_switch


def _handle_confirm_switch_anchor(
    req: "Any", session: Any, reader: Any, hints: dict,
) -> dict[str, Any] | None:
    """Returns None when the switch completes successfully — the caller
    falls through to STEP 1, which re-anchors the country for the new
    product only if it's still empty (a validated carried-over country
    is preserved, never re-asked).
    """
    from aryx.api import ask_api as _ask_api_module
    reply = req.question.strip().lower()
    # Affirmative includes replying with the offered product's own name
    # ("videoSolutions_BOM" to "switch to videoSolutions_BOM?") — a
    # natural way to accept that previously counted as a decline.
    _pending_norm = re.sub(r"[^a-z0-9]", "", session.pending_switch_product.lower())
    affirmative = (
        reply.startswith(("y", "yes", "switch", "confirm"))
        or (_pending_norm and re.sub(r"[^a-z0-9]", "", reply) == _pending_norm)
    )
    # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row 21: a
    # genuinely ambiguous reply ("maybe", "I guess", "not sure") is
    # neither a clear yes nor a clear no — tried only for what's left
    # after the clear-no check below, mirroring the same "deterministic
    # first, narrow LLM fallback only for what's actually ambiguous"
    # discipline as every other fix this session. A clear "no"/"nope"/
    # "never" never reaches the LLM at all — cheap and unambiguous
    # enough that asking would be pure cost with no benefit.
    _clear_decline = bool(re.match(
        r"^\s*(n|no|nope|nah|never|not\s+now|not\s+really)\b",
        reply, re.IGNORECASE,
    ))
    if not affirmative and not _clear_decline:
        _switch_decision = _llm_classify_switch_reply(
            req.question, session.pending_switch_product,
            session.product_name, req.workspace_id,
        )
        if _switch_decision == "accept":
            affirmative = True
    _ask_api_module.logger.info(
        "cpq_switch: confirm-reply turn=%s current=%r pending=%r reply=%r decision=%s",
        session.turn, session.product_name, session.pending_switch_product,
        req.question, "switch" if affirmative else "stay",
    )
    if affirmative:
        new_product = session.pending_switch_product
        old_country = session.country
        if old_country and not _country_available_for(
            reader, req.workspace_id, new_product, old_country,
        ):
            session.pending_anchor = "switch_country"
            _ask_api_module.logger.info(
                "cpq_switch: country=%r invalid for new_product=%r turn=%s — "
                "asking for a different country before completing the switch",
                old_country, new_product, session.turn,
            )
            answer = (
                f"**{new_product}** isn't available for **{old_country}**. "
                f"Could you provide a different country to continue switching?"
            )
            _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
            return {
                "answer": answer, "terms": [], "tools_called": ["cpq_switch_country_invalid()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
        _complete_product_switch(session, new_product, old_country)
        # Fall through — Step 1's anchor block below re-anchors the
        # country for the new product only if it's still empty (a
        # validated carried-over country is preserved, never re-asked).
        return None
    return _handle_confirm_switch_decline(req, session, reader, hints)
