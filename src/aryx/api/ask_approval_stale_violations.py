"""Handling the final BOM gate's stale-constraint-violation and genuine-
rule-conflict outcomes for `_handle_approval`, split out of `api/
ask_api.py` (Phase 5/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling `ask_handle_
approval.py` under the line cap. Logic unchanged from the original
inline block. `_cpq_engine` and `_persist_cpq_history` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.cpq.session_guard import push_snapshot


def _handle_approval_gate_conflict(
    req: "Any", session: Any, attrs: list, gate: Any,
) -> dict[str, Any] | None:
    """docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §15 —
    multiple active constraints can legitimately intersect to an EMPTY
    allowed set (a genuine rule conflict, not a stale-but-fixable value).
    Reports the conflict instead of an unanswerable re-ask loop; nothing
    is mutated. Returns None when there is no genuine conflict, in which
    case the caller proceeds to the stale-but-fixable re-ask branch.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _conflicted = [v for v in gate.stale_violations if not v.allowed]
    if not _conflicted:
        return None
    _conflict_labels = [
        _cpq_engine.disambiguated_label(v.attr, attrs) for v in _conflicted
    ]
    answer = (
        "⚠️ **Rule conflict detected.**\n\n"
        + (
            f"**{_conflict_labels[0]}** has no valid options "
            if len(_conflict_labels) == 1 else
            "The following have no valid options "
            + ", ".join(f"**{l}**" for l in _conflict_labels) + " "
        )
        + "left, given your other selections — the active "
        "rules conflict with each other.\n\nPlease change one "
        "of your earlier selections, or say **undo** to "
        "restore the previous snapshot."
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_rule_conflict()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _handle_approval_stale_reask(
    req: "Any", session: Any, attrs: list, gate: Any,
) -> dict[str, Any]:
    """docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §11/§12 —
    auto-clear + re-ask rather than hard-block; push_snapshot before
    mutating so "undo" reverts just this clear.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    push_snapshot(session, reason="stale_constraint_reask")
    _stale_display: dict[str, str] = {}
    _stale_vns: list[str] = []
    for _v in gate.stale_violations:
        _vn = _v.attr.variable_name
        _stale_display[_vn] = session.display_filled.get(_vn) or _v.current_value
        if _v.attr.select_type == "multi":
            _kept = [
                iv for iv in session.filled_multi.get(_vn, []) if iv in _v.allowed
            ]
            if _kept:
                session.filled_multi[_vn] = _kept
                session.display_filled[_vn] = ", ".join(
                    next((o.display_name for o in _v.attr.options if o.item_value == iv), iv)
                    for iv in _kept
                )
            else:
                session.filled_multi.pop(_vn, None)
                session.display_filled.pop(_vn, None)
        else:
            session.filled.pop(_vn, None)
            session.display_filled.pop(_vn, None)
        session.filled_source.pop(_vn, None)
        _stale_vns.append(_vn)
    session.pending_variables = _stale_vns + [
        v for v in session.pending_variables if v not in _stale_vns
    ]
    session.status = "configuring"
    session.complete = False
    _first = gate.stale_violations[0]
    _stale_opts_prompt = _cpq_engine.next_question_prompt(
        _first.attr, constrained_item_values=_first.allowed, attrs=attrs,
    )
    _rest_labels = [
        _cpq_engine.disambiguated_label(_v.attr, attrs) for _v in gate.stale_violations[1:]
    ]
    _also_note = (
        f"\n\n*(I'll also ask about {', '.join(f'**{l}**' for l in _rest_labels)} next.)*"
        if _rest_labels else ""
    )
    answer = (
        f"A couple of your earlier selections no longer match your "
        f"other choices — let's update "
        f"{'them' if _rest_labels else 'it'} before I generate the BOM.\n\n"
        f"**{_cpq_engine.disambiguated_label(_first.attr, attrs)}** is "
        f"currently *{_stale_display[_first.attr.variable_name]}*, which "
        f"isn't valid anymore given your other choices:\n\n"
        f"{_stale_opts_prompt}{_also_note}"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_stale_constraint_reask()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
