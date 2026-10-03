""""Which value would you like for X?" follow-up response builder, split
out of `api/ask_api.py` (Phase 3/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline definition. `_cpq_engine` and `_persist_cpq_history` are
read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path; the other helpers below are not patched anywhere and are imported
directly (this import must stay textually AFTER their own definitions in
ask_api.py, since it's a plain by-name import, not a whole-module one).
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_intent_queue_text_helpers import _append_unmatched_targets_note, _apply_intent_conservation, _queue_followup_note, _scan_and_enqueue_remaining_targets
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.cpq.session_guard.session_guard import clear_queue_vn
from aryx.raven_log import raven_log


def _build_no_value_response(
    req: "Any",
    session: Any,
    attrs: list,
    target_attr: Any,
    con_rules: list,
    bml_eval: Any,
    tool_name: str,
) -> dict[str, Any]:
    """"Which value would you like for X?" follow-up for a change-verb
    naming an already-filled attribute with no resolvable new value.

    Shared by two callers (2026-07-28 refactor): the regex-based
    `detect_change_target_without_value` and the LLM change-intent
    fallback's own empty-value case ("change the hardware type" correctly
    identifies hWVersion_astro but states no new value) — previously the
    LLM path had no equivalent and silently discarded a correctly-
    identified target instead of asking, the same class of gap
    `detect_change_target_without_value` already closed for its own regex
    matches.

    Also scans the utterance for additional named targets and enqueues
    them on pending_intent_queue so multi-target "change A, B and C"
    asks each in sequence.
    """
    # Enqueue every OTHER named no-value target in this utterance.
    from aryx.api import ask_api as _ask_api_module
    enqueued, _overflow = _scan_and_enqueue_remaining_targets(
        session, req.question, attrs,
        exclude_vns={target_attr.variable_name},
    )
    # Active target is not "queued" — it's pending_change_no_value.
    clear_queue_vn(session, target_attr.variable_name)

    _cpq_engine = _ask_api_module._cpq_engine
    constrained = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval, filled_multi=session.filled_multi)
    options_block = _cpq_engine.next_question_prompt(
        target_attr, constrained_item_values=constrained.get(target_attr.entity_id),
        attrs=attrs,
    )
    current_val = session.filled.get(target_attr.variable_name)
    current_note = (
        f"\n\n*Currently set to: **"
        f"{session.display_filled.get(target_attr.variable_name, current_val)}***"
        if current_val else ""
    )
    answer = (
        f"Which value would you like for "
        f"**{_cpq_engine.disambiguated_label(target_attr, attrs)}**?"
        f"\n\n{options_block}{current_note}"
    )
    answer += _queue_followup_note(session, attrs)
    session.pending_change_no_value_vn = target_attr.variable_name
    detected = {target_attr.variable_name} | set(enqueued) | set(
        session.pending_intent_queue or [],
    )
    # Also count overflow as detected for conservation (must not silently drop)
    if _overflow:
        detected |= set(_overflow)
    result = _append_unmatched_targets_note(
        {
            "answer": answer, "terms": [target_attr.variable_name],
            "tools_called": [f"{tool_name}({target_attr.variable_name})"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        },
        req.question, attrs, {target_attr.variable_name},
    )
    result = _apply_intent_conservation(
        result, req.question, detected,
        handled_vns=set(),  # none applied yet
        session=session, attrs=attrs,
        clarified_vns={target_attr.variable_name},
    )
    raven_log("INFO", "P4", "ask.response.no_value asked which value for change target", context={
        "selected_option": "ask_which_value", "reason_code": "CHANGE_TARGET_WITHOUT_VALUE",
        "turn": getattr(session, "turn", None), "run_id": getattr(session, "run_id", None),
        "target_vn": getattr(target_attr, "variable_name", None), "tool_name": tool_name,
        "has_current_value": bool(current_val), "enqueued_count": len(enqueued or []),
        "overflow_count": len(_overflow or []), "detected_count": len(detected),
        "queue_len": len(getattr(session, "pending_intent_queue", None) or []),
        "answer_len": len(str(result.get("answer") or "")) if isinstance(result, dict) else None})
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, result["answer"])
    return result
