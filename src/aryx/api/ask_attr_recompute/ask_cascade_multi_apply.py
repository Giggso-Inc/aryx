"""Applying every named change in one multi-target cascade turn, split
out of `_handle_cascade_multi` (Phase 4/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the
sibling `ask_handle_cascade_multi.py` under the line cap. Logic
unchanged from the original inline block. `_cpq_engine` is read through
the ask_api MODULE object (not imported by name) since at least one test
replaces the whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model import _invalidate_stale_base_model
from aryx.cpq.session_guard.session_guard import clear_queue_vn, enqueue_intent_targets
from aryx.cpq.state import INTENT_QUEUE_CAP


def _apply_cascade_multi_changes(
    req: "Any", session: Any, attrs: list, matches: list, by_eid: dict,
    hiding_rules: list, rec_rules: list, con_rules: list,
) -> tuple:
    """Applies each named change (up to `detect_change_requests_multi`'s
    cap) one at a time, stripping each attr's own cascade dependents from
    session state before re-applying (same as the single-change path) --
    a dependent can be select_type=="multi" (real value lives in
    filled_multi, never filled), so both are popped unconditionally.
    Product decision: partial apply -- whichever named changes parse are
    applied; any that don't are queued for a follow-up ask, never
    silently dropped and never rejecting the whole turn.

    Returns (applied_notes, failed_labels, all_dependent_eids, changed_vns,
    user_requested_single) -- single-select applies are tracked in
    `user_requested_single` rather than noted immediately, since D1
    (docs/CPQ_USER_VALUE_PRECEDENCE_PLAN.md) requires checking them
    against the outcome AFTER the rule pass the caller runs next.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    applied_notes: list[str] = []
    failed_labels: list[str] = []
    all_dependent_eids: set[int] = set()
    changed_vns: set[str] = set()
    user_requested_single: dict[str, tuple[Any, str, str]] = {}

    for changed_attr, new_value_hint in matches:
        if changed_attr.variable_name in changed_vns:
            continue  # same attr matched twice in one message — apply once

        dependent_eids = _cpq_engine.find_cascade_dependents(
            changed_attr, attrs, hiding_rules, rec_rules, con_rules,
        )
        session.filled.pop(changed_attr.variable_name, None)
        session.display_filled.pop(changed_attr.variable_name, None)
        session.filled_source.pop(changed_attr.variable_name, None)
        for eid in dependent_eids:
            a = by_eid.get(eid)
            if a:
                session.filled.pop(a.variable_name, None)
                session.filled_multi.pop(a.variable_name, None)
                session.display_filled.pop(a.variable_name, None)
                session.filled_source.pop(a.variable_name, None)
        _invalidate_stale_base_model(
            session, changed_attr, dependent_eids, by_eid, req.workspace_id,
            attrs[0].catalog_prefix if attrs else "",
        )

        if changed_attr.select_type == "multi":
            mentioned = _cpq_engine.apply_multi_answer(changed_attr, new_value_hint)
            result = ("", "") if not mentioned else mentioned[0]
            if mentioned:
                existing = session.filled_multi.get(changed_attr.variable_name, [])
                merged = list(existing) + [iv for iv, _dn in mentioned if iv not in existing]
                session.filled_multi[changed_attr.variable_name] = merged
                session.display_filled[changed_attr.variable_name] = ", ".join(
                    next((o.display_name for o in changed_attr.options if o.item_value == v), v)
                    for v in merged
                )
                session.filled_source[changed_attr.variable_name] = "user"
            else:
                result = None
        else:
            result = _cpq_engine.apply_answer(changed_attr, new_value_hint)
            if result:
                session.filled[changed_attr.variable_name] = result[0]
                session.display_filled[changed_attr.variable_name] = result[1]
                session.filled_source[changed_attr.variable_name] = "user"

        if not result:
            # Ask, don't report: queue unparsable targets so we solicit a
            # value on the next turn instead of dead-ending in failed_labels.
            failed_labels.append(changed_attr.display_label)
            enqueue_intent_targets(
                session, [changed_attr.variable_name], cap=INTENT_QUEUE_CAP,
            )
            continue

        changed_vns.add(changed_attr.variable_name)
        clear_queue_vn(session, changed_attr.variable_name)
        all_dependent_eids |= set(dependent_eids)
        if changed_attr.select_type == "multi":
            changed_disp = session.display_filled.get(changed_attr.variable_name, new_value_hint)
            applied_notes.append(
                f"Updated **{_cpq_engine.disambiguated_label(changed_attr, attrs)}** "
                f"→ **{changed_disp}**."
            )
        else:
            # Note built after the rule pass below, once we know whether
            # this value actually stuck (D1).
            user_requested_single[changed_attr.variable_name] = (
                changed_attr, result[0], result[1],
            )
    return applied_notes, failed_labels, all_dependent_eids, changed_vns, user_requested_single
