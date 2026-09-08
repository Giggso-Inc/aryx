"""Building the re-ask prompt for genuinely stale (but fixable) constraint
violations, split out of `ask_stale_constraint_reask.py` (Phase 4/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Logic unchanged from the original inline block. `_cpq_engine` is read
through the ask_api MODULE object (not imported by name) since at least
one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.pending_scope import set_pending_scope
from aryx.cpq.session_guard import push_snapshot


def build_stale_reask_prompt(session: Any, attrs: list, stale: list) -> str:
    """Clears and re-queues every still-stale attribute (mirroring the
    conflicted branch's own accounting), then builds the re-ask prompt
    for the first one — narrowed to whatever the fresh recheck still
    allows.
    """
    from aryx.api import ask_api as _ask_api_module
    push_snapshot(session, reason="stale_constraint_reask")
    stale_vns: list[str] = []
    for v in stale:
        vn = v.attr.variable_name
        if v.attr.select_type == "multi":
            kept = [iv for iv in session.filled_multi.get(vn, []) if iv in v.allowed]
            if kept:
                session.filled_multi[vn] = kept
                session.display_filled[vn] = ", ".join(
                    next((o.display_name for o in v.attr.options if o.item_value == iv), iv)
                    for iv in kept
                )
            else:
                session.filled_multi.pop(vn, None)
                session.display_filled.pop(vn, None)
        else:
            session.filled.pop(vn, None)
            session.display_filled.pop(vn, None)
        session.filled_source.pop(vn, None)
        stale_vns.append(vn)
    session.pending_variables = stale_vns + [
        v for v in session.pending_variables if v not in stale_vns
    ]
    session.status = "configuring"
    session.complete = False
    first = stale[0]
    prompt = _ask_api_module._cpq_engine.next_question_prompt(
        first.attr, constrained_item_values=first.allowed, attrs=attrs,
    )
    # 2026-08-18 fix (sibling gap to _reask_confirmed_data_table_conflict's
    # own fix): sync pending_scope to the narrowed list just shown above,
    # or the next reply gets validated against whatever candidates were
    # left over from BEFORE this re-ask -- same "stale scope rejects a
    # verbatim answer" bug, just harder to trigger here since it only
    # shows when `first.allowed` narrows to 2+ options (a 1-option case,
    # the common shape for this branch, can't expose it since any answer
    # either matches the sole option or doesn't).
    allowed_set = set(first.allowed or ())
    set_pending_scope(
        session,
        kind="attr_options",
        candidates=[
            o.display_name for o in first.attr.options
            if not allowed_set or o.item_value in allowed_set
        ],
        origin_question=prompt,
        attr_vn=first.attr.variable_name,
        asked_turn=session.turn,
    )
    first_label = _ask_api_module._cpq_engine.disambiguated_label(first.attr, attrs)
    rest_labels = [
        _ask_api_module._cpq_engine.disambiguated_label(v.attr, attrs) for v in stale[1:]
    ]
    also_note = (
        f"\n\n*(I'll also ask about {', '.join(f'**{l}**' for l in rest_labels)} next.)*"
        if rest_labels else ""
    )
    return (
        f"Before finishing — **{first_label}** is no longer valid given "
        f"your other selections.\n\n{prompt}{also_note}"
    )
