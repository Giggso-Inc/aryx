"""Multi-target intent-queue text helpers, split out of `ask_api.py`
(final sweep, Phase 11/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). `_append_unmatched_targets_note`
surfaces (never silently drops) a fragment of a multi-target change
request that named nothing real — called at every STEP 6 change-request
dispatch site right after the real change succeeds, so the note rides
along with the genuine answer rather than blocking it.
`_scan_and_enqueue_remaining_targets` scans the utterance for every
valueless change target and enqueues all but the active one.
`_apply_intent_conservation` runs the intent-conservation audit and
appends a dropped-intent notice when something named in the message was
never actually handled. Logic unchanged from the original inline
definitions. `_cpq_engine` is read through the ask_api module object
(not imported by name) since at least one test replaces the whole
singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.session_guard import (
    audit_intent_conservation,
    enqueue_intent_targets,
    format_dropped_intent_notice,
    format_queue_overflow_notice,
)
from aryx.cpq.state import INTENT_QUEUE_CAP



def _append_unmatched_targets_note(
    result: dict, question: str, attrs: list, matched_vns: "set[str]",
) -> dict:
    """Surfaces (never silently drops) a fragment of a multi-target
    change request that named nothing real."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    unmatched = _cpq_engine.detect_unmatched_change_targets(question, attrs, matched_vns)
    if unmatched:
        phrases = ", ".join(f'"{u}"' for u in unmatched)
        result["answer"] += (
            f"\n\n*(I didn't recognize {phrases} as anything in this "
            f"configuration — did you mean something else?)*"
        )
    return result


def _scan_and_enqueue_remaining_targets(
    session: Any,
    question: str,
    attrs: list,
    *,
    exclude_vns: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Scan utterance for all valueless change targets; enqueue all but
    active. Returns (enqueued_vns, overflow_vns)."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    exclude = set(exclude_vns or set())
    all_targets = _cpq_engine.detect_all_change_targets_without_value(
        question, attrs, session.filled,
        filled_multi=session.filled_multi,
        exclude_vns=exclude,
        cap=INTENT_QUEUE_CAP + 5,  # detect a few past cap so overflow is visible
    )
    remaining = [a.variable_name for a in all_targets if a.variable_name not in exclude]
    overflow = enqueue_intent_targets(
        session, remaining, exclude=exclude, cap=INTENT_QUEUE_CAP,
    )
    enqueued = [v for v in remaining if v in session.pending_intent_queue]
    return enqueued, overflow


def _queue_followup_note(session: Any, attrs: list) -> str:
    """Human note listing queued targets still to ask."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if not session.pending_intent_queue:
        note = ""
    else:
        by_vn = {a.variable_name: a for a in attrs}
        labels = [
            _cpq_engine.disambiguated_label(by_vn[v], attrs)
            if v in by_vn else v
            for v in session.pending_intent_queue
        ]
        if len(labels) == 1:
            note = f"\n\n*(I'll also ask about **{labels[0]}** next.)*"
        else:
            joined = ", ".join(f"**{lbl}**" for lbl in labels)
            note = f"\n\n*(I'll ask about each next: {joined}.)*"
    if session.pending_intent_overflow:
        note += "\n\n" + format_queue_overflow_notice(
            list(session.pending_intent_overflow), attrs,
        )
        session.pending_intent_overflow = []
    return note


def _apply_intent_conservation(
    result: dict[str, Any] | None,
    question: str,
    detected_targets: set[str] | list[str],
    handled_vns: set[str] | list[str],
    session: Any,
    attrs: list,
    *,
    clarified_vns: set[str] | list[str] | None = None,
) -> dict[str, Any] | None:
    """Run intent-conservation audit; append dropped-intent notice to answer."""
    if result is None:
        return None
    audit = audit_intent_conservation(
        question, detected_targets, handled_vns, session,
        clarified_vns=clarified_vns,
        run_id=getattr(session, "run_id", "") or "",
        turn=int(getattr(session, "turn", 0) or 0),
        log=True,
    )
    if audit.dropped:
        notice = format_dropped_intent_notice(audit.dropped, attrs)
        if notice:
            result["answer"] = (result.get("answer") or "") + "\n\n" + notice
        result["session_data"] = session.to_dict()
        tools = list(result.get("tools_called") or [])
        tools.append("cpq_intent_dropped()")
        result["tools_called"] = tools
    return result
