"""Handling for a genuine rule conflict (2+ active constraints intersect
to nothing) discovered during the stale-constraint proactive re-ask,
split out of `ask_stale_constraint_reask.py` (Phase 4/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline block. `_cpq_engine` is read through
the ask_api MODULE object (not imported by name) since at least one test
replaces the whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.cpq.session_guard import push_snapshot


def handle_conflicted_violations(session: Any, attrs: list, conflicted: list) -> str:
    """A stale violation whose replacement set is ALSO empty is a genuine
    rule conflict, not a stale-but-fixable value — same distinction
    confirm's own gate makes (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_
    CLARIFY_ISSUE.md §15). Asking a question with zero valid options
    would just reproduce the exact unanswerable "Please provide a value"
    dead-end this session's other fixes exist to prevent — report the
    conflict instead of building a narrowed prompt.

    The stale value(s) ARE still cleared and re-queued here (2026-08-19
    fix — live-confirmed via a real APX NEXT transcript: Package Type
    vs Product left in exactly this branch), mirroring the sibling
    `stale` branch. Before this fix nothing was mutated, so a conflicted
    attribute stayed sitting in session.filled with its stale (now-
    invalid) value and was never re-queued through this function's own
    accounting — the next turn's ask for it fell through to a generic,
    less-informed re-ask path that has no knowledge of the conflict and
    presented the FULL raw catalog list instead of anything narrowed,
    confusing the user into re-picking from scratch. Clearing +
    re-queuing here doesn't fix the unanswerable-with-zero-options
    problem (that's inherent to a real conflict), but it does mean the
    attribute is no longer stuck holding stale data, and the subsequent
    ask goes through the standard pending-attr flow with the OTHER
    conflicting side already known, giving the constraint engine a real
    chance to narrow it.
    """
    conflict_labels = [
        _ask_api_module._cpq_engine.disambiguated_label(v.attr, attrs) for v in conflicted
    ]
    push_snapshot(session, reason="stale_constraint_conflict_reask")
    conflicted_vns: list[str] = []
    for v in conflicted:
        vn = v.attr.variable_name
        if v.attr.select_type == "multi":
            session.filled_multi.pop(vn, None)
        else:
            session.filled.pop(vn, None)
        session.display_filled.pop(vn, None)
        session.filled_source.pop(vn, None)
        conflicted_vns.append(vn)
    session.pending_variables = conflicted_vns + [
        v for v in session.pending_variables if v not in conflicted_vns
    ]
    session.status = "configuring"
    session.complete = False
    if len(conflict_labels) == 1:
        return (
            f"⚠️ **Rule conflict detected.** **{conflict_labels[0]}** has "
            f"no valid options left, given your other selections — the "
            f"active rules conflict with each other. Please change one "
            f"of your earlier selections."
        )
    return (
        "⚠️ **Rule conflict detected.** The following have no valid "
        "options left, given your other selections: "
        + ", ".join(f"**{l}**" for l in conflict_labels)
        + " — the active rules conflict with each other. Please change "
        "one of your earlier selections."
    )
