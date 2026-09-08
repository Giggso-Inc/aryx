"""STEP 6 (multi) handler — applying every change a single message names
at once, split out of `api/ask_api.py` (Phase 4/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition; every stage lives in a
sibling `ask_cascade_multi_*.py` file purely to keep this file under the
line cap. `_cpq_engine` and `_build_no_value_response` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_build_no_value_response import _build_no_value_response
from aryx.api.ask_cascade_multi_apply import _apply_cascade_multi_changes
from aryx.api.ask_cascade_multi_note import (
    _build_cascade_multi_note,
    _revert_overridden_multi_singles,
)
from aryx.api.ask_cascade_multi_recompute import _recompute_after_cascade_multi
from aryx.api.ask_cascade_multi_response import _build_cascade_multi_response
from aryx.cpq.session_guard import drain_intent_queue_into_pending, push_snapshot


def _handle_cascade_multi(
    req: "Any",
    session: Any,
    attrs: list,
    matches: list,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> "dict[str, Any] | None":
    """STEP 6 (multi) — apply every change a single message names at once
    (up to `detect_change_requests_multi`'s cap), union their cascade
    dependents, then re-run the rule loop ONCE — not once per change, or a
    dependent could get re-derived against a stale intermediate state
    between two changes applied in the same turn.

    Product decision: partial apply. Whichever of the named changes parse
    (a real value found for that attr) are applied; any that don't are
    reported by label, not silently dropped and not rejecting the whole
    turn. Returns None (caller falls through to the normal "didn't catch
    that" nudge) only when NONE of the named changes could be applied —
    mirrors `detect_change_request` returning None today.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    push_snapshot(session, reason="cascade_multi")
    by_eid = {a.entity_id: a for a in attrs}
    hints = _cpq_engine.extract_hints(req.question)
    catalog_hints, negated_now = _cpq_engine.extract_catalog_hints(req.question, attrs)
    for vn, iv in catalog_hints.items():
        hints.setdefault(vn, iv)
    catalog_prefix = attrs[0].catalog_prefix if attrs else ""
    for vn, iv in _cpq_engine.extract_flag_hints(
        req.question, attrs, req.workspace_id, catalog_prefix,
    ).items():
        hints.setdefault(vn, iv)
    session.negated_vns = sorted(set(session.negated_vns) | negated_now)
    negated_vns = set(session.negated_vns)

    applied_notes, failed_labels, all_dependent_eids, changed_vns, user_requested_single = (
        _apply_cascade_multi_changes(
            req, session, attrs, matches, by_eid, hiding_rules, rec_rules, con_rules,
        )
    )

    if not changed_vns and not session.pending_intent_queue:
        # None of the named changes could be applied at all — let the
        # caller fall through to the normal "didn't catch that" nudge,
        # same as detect_change_request returning None.
        return None
    if not changed_vns and session.pending_intent_queue:
        # All targets lacked parseable values — ask the first queued one.
        head_vn = session.pending_intent_queue[0]
        head_attr = next((a for a in attrs if a.variable_name == head_vn), None)
        if head_attr is not None:
            bml_eval_nv = _cpq_engine.build_bml_evaluator(
                req.workspace_id, attrs[0].catalog_prefix if attrs else "",
            )
            return _build_no_value_response(
                req, session, attrs, head_attr, con_rules, bml_eval_nv,
                "cpq_cascade_multi_queue_ask",
            )
        return None

    # set_type=="2" attrs never re-enter filled/pending after this rerun
    # and are always excluded from the final payload — see _handle_cascade's
    # identical filter for the live-verified finding this addresses.
    dependent_labels = [
        _cpq_engine.disambiguated_label(by_eid[eid], attrs) for eid in all_dependent_eids
        if eid in by_eid and by_eid[eid].variable_name not in changed_vns
        and by_eid[eid].set_type != "2"
    ]

    (
        visible_attrs, filled, display_filled, constrained_opts, pending,
        rule_ids, bml_eval, dropped_multi,
    ) = _recompute_after_cascade_multi(
        req, session, attrs, changed_vns, hints, negated_vns, catalog_prefix,
        hiding_rules, rec_rules, con_rules,
    )

    pending = _revert_overridden_multi_singles(
        session, attrs, user_requested_single, applied_notes, pending,
    )

    # Drain queue head to front of pending (same convergence as single cascade).
    pending = drain_intent_queue_into_pending(session, pending, visible_attrs)

    cascade_note = _build_cascade_multi_note(
        attrs, applied_notes, failed_labels, dependent_labels, dropped_multi,
    )

    return _build_cascade_multi_response(
        req, session, attrs, hiding_rules, rec_rules, con_rules, cascade_note,
        visible_attrs, filled, display_filled, constrained_opts, pending,
        rule_ids, bml_eval, catalog_prefix,
    )
