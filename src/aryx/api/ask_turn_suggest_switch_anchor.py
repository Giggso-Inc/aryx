"""Handling a reply to the "suggest_switch" pending anchor (a prior turn
offered several "did you mean...?" product families), split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline `if` block. `_persist_cpq_history` is read through the
ask_api MODULE object (not imported by name) since ask_api tests patch
several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _handle_suggest_switch_anchor(req: "Any", session: Any) -> dict[str, Any] | None:
    """A prior turn offered SEVERAL "did you mean...?" families — a bare
    "yes" can't pick one of 2+, so re-prompt with the list instead of
    guessing. A "no" (or any other text) clears the state and falls
    through (returns None) to normal handling — a reply naming one of the
    candidates is then caught by regular switch detection later this same
    turn, which routes it into the standard confirm_switch flow.
    """
    _sreply = req.question.strip().lower()
    if _sreply.startswith(("y", "yes")):
        cand_list = ", ".join(f"**{c}**" for c in session.pending_switch_candidates)
        answer = (
            f"Which one did you mean: {cand_list}? Reply with the "
            f"product name — or say **no** to continue with "
            f"**{session.product_name}**."
        )
        _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_switch_ambiguous()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    session.pending_anchor = ""
    session.pending_switch_candidates = []
    if _sreply.startswith(("n", "no")):
        answer = f"OK — continuing with **{session.product_name}**."
        _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_switch_declined()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    # Anything else falls through — normal turn handling (including
    # switch detection on a candidate name) takes over.
    return None
