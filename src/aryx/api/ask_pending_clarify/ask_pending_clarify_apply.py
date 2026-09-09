"""Clearing pending-clarify state and replaying the original vague
utterance against a just-resolved attribute, split out of `api/ask_api.py`
(Phase 2/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline
definitions. `_cpq_engine`, `_persist_cpq_history`, `_handle_cascade`, and
`_build_no_value_response` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch each of these by dotted
path (`patch("aryx.api.ask_api.<name>")` / `patch.object(api, "<name>")`).
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_response_building.ask_build_no_value_response import _build_no_value_response
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_handle import ask_handle_cascade as _ask_handle_cascade_module
from aryx.cpq.session_guard.session_guard import clear_clarify


def _clear_pending_clarify(session: Any) -> None:
    session.pending_clarify_vns = []
    session.pending_clarify_question = ""
    session.pending_clarify_prompt = ""
    session.pending_clarify_asked_turn = 0
    session.pending_clarify_misses = 0


def _apply_pending_clarify_resolution(
    req: "Any",
    session: Any,
    attrs: list,
    resolved_vn: str,
    orig_question: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
    bml_eval: Any,
) -> dict[str, Any]:
    """Replay the original vague utterance against the resolved attribute."""
    from aryx.api import ask_api as _ask_api_module
    _clear_pending_clarify(session)
    clear_clarify(session, resolved_vn)
    # Remember this resolution as the anchor for a later bare-value reply
    # that's ambiguous across several candidates by itself (issue 4).
    session.last_clarified_attr_vn = resolved_vn
    session.last_clarified_turn = int(session.turn or 0)
    resolved_attr = next((a for a in attrs if a.variable_name == resolved_vn), None)
    if resolved_attr is None:
        answer = (
            f"I couldn't load the attribute `{resolved_vn}` from this catalog. "
            "Please name the field again."
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_pending_clarify_missing_attr()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # Prefer applying a value from the CURRENT reply first — "SmartProgramming
    # 2 Yrs" replying to "which attribute did you mean?" already IS the
    # answer, not just a label, and discarding it in favor of stale text
    # from an earlier turn silently threw the value away (confirmed live:
    # the resolved attribute re-asked for its value and reported the OLD
    # one as still "current" even though the customer had just supplied a
    # new one in this exact reply). Fall back to the ORIGINAL vague
    # utterance only when the current reply itself carries no value — the
    # pre-existing case of a bare label reply ("Hardware Version") following
    # an earlier message that already had the value ("change hardware to
    # 4G LTE Only"), where the value lives in that earlier text, not the
    # reply that merely names the attribute.
    change = _ask_api_module._cpq_engine.detect_change_request(
        req.question, [resolved_attr], session.filled,
        filled_multi=session.filled_multi,
    )
    if not change and req.question != orig_question:
        change = _ask_api_module._cpq_engine.detect_change_request(
            orig_question, [resolved_attr], session.filled,
            filled_multi=session.filled_multi,
        )
    if change:
        _attr, value_hint = change
        return _ask_handle_cascade_module._handle_cascade(
            req, session, attrs, _attr, value_hint,
            hiding_rules, rec_rules, con_rules,
        )
    # Valueless change ("change hardware") → ask which value for the
    # now-resolved attribute (same helper as regex/LLM no-value paths).
    return _build_no_value_response(
        req, session, attrs, resolved_attr, con_rules, bml_eval,
        "cpq_pending_clarify_resolved",
    )
