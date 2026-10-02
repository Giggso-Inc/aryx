"""Re-running the full hide->recommend->constrain->auto-fill loop after a
STEP-6 cascade change, reconciling session state, draining the multi-
target intent queue, and reverting a rule-pass override of the
customer's just-chosen value, split out of `_handle_cascade` (Phase 4/
11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md) purely to keep the sibling `ask_handle_cascade.py` under the line
cap. Logic unchanged from the original inline block. `_cpq_engine` is
read through the ask_api MODULE object (not imported by name) since at
least one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_cascade_user_value_precedence import _revert_overridden_user_value
from aryx.cpq.grid_quantity.narrow import grid_narrow_kwargs
from aryx.cpq.session_guard.session_guard import clear_queue_vn, drain_intent_queue_into_pending


def _recompute_after_cascade(
    req: "Any", session: Any, attrs: list, changed_attr: Any, result: tuple,
    hints: dict, negated_vns: set, catalog_prefix: str,
    hiding_rules: list, rec_rules: list, con_rules: list,
) -> tuple:
    """Re-runs the full rule evaluation loop with the just-updated state,
    logs every cascade-caused value change, reconciles session state,
    drains the multi-target intent queue, then reverts a rule-pass
    override of the customer's just-chosen value (D1, docs/CPQ_USER_
    VALUE_PRECEDENCE_PLAN.md) if one occurred. Returns (visible_attrs,
    filled, display_filled, constrained_opts, pending, rule_ids, bml_eval,
    dropped_multi, user_value_overridden, requested_display).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    prev_filled_snapshot = dict(session.filled)
    dropped_multi: dict[str, list[str]] = {}
    skip_always_ask = _cpq_engine.resolve_always_ask_skips(
        req.workspace_id, catalog_prefix, attrs)
    # Amendment 10 follow-up, extended to cascade turns (found live
    # 2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): the
    # resolved-model-leaf -> skip "Product"-labeled attrs protection only
    # ever existed in _run_cpq_turn's own pending computation — a change
    # request processed here in _handle_cascade had no such guard, so a
    # customer requesting an unrelated change (e.g. FedRamp) could still
    # be asked the raw-variable-name "Product" label collision this
    # protection exists specifically to suppress.
    if session.model_leaf_resolved:
        skip_always_ask = skip_always_ask | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)
    visible_attrs, filled, display_filled, constrained_opts = _cpq_engine.evaluate_rules_loop(
        attrs, hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
        rule_conflict_order=_cpq_engine._load_layout_full_order(req.workspace_id, catalog_prefix),
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
    )
    governed_ids = _cpq_engine.governed_target_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    rule_ids = _cpq_engine.rule_governed_ids(visible_attrs, hiding_rules, rec_rules, con_rules)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    filled, display_filled, pending = _cpq_engine.auto_fill(
        visible_attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
        governed_ids=governed_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, country=session.country, rule_governed_ids=rule_ids,
        negated_vns=negated_vns, filled_source=session.filled_source,
        skip_always_ask=skip_always_ask, bml_eval=bml_eval,
        validation_rules=validation_rules,
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
        hiding_rules=hiding_rules,
        grid_declined_vns=frozenset(session.pending_grid_declined_vns),
    )
    if session.model_leaf_resolved:
        # skip_always_ask only suppresses the always-ask OVERRIDE — it
        # doesn't stop a genuinely required, no-default attr from staying
        # "pending" outright. Same cascade-turn parity fix as above.
        pending = [
            a for a in pending
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                attrs, hiding_rules, rec_rules, con_rules)
        ]
    pending = _cpq_engine.append_pending_grid_quantities(
        pending, visible_attrs, filled, session.filled_multi, session.filled_source,
        constrained_opts, **grid_narrow_kwargs(req.workspace_id, catalog_prefix))
    for var, new_val in filled.items():
        old_val = prev_filled_snapshot.get(var)
        if old_val != new_val:
            session.cascade_log.append({
                "var": var, "old": old_val, "new": new_val,
                "rule": "cascade" if var == changed_attr.variable_name else "cascade-dependent",
                "turn": session.turn,
            })
    session.filled = filled
    session.display_filled = display_filled
    session.pending_variables = [a.variable_name for a in pending]
    session.filled_source = {
        k: v for k, v in session.filled_source.items()
        if k in filled or k in session.filled_multi
    }
    session.filled_multi = {
        k: v for k, v in session.filled_multi.items()
        # Keep a value dormant rather than purge it just because it isn't
        # part of THIS turn's visible set — a multi-select auto-defaulted
        # before an upstream required attr (Product, Base Model, ...) is
        # answered gets hidden by "if Product is blank"-style rules for
        # exactly that one turn, then never re-populated once it becomes
        # visible again since nothing re-triggers the original default-pick
        # a second time. Only drop entries the cascade explicitly
        # invalidated this turn (`dropped_multi`, real conflicts, already
        # surfaced to the customer) or that no longer exist in the catalog
        # at all — never a value that's merely temporarily hidden.
        if k not in dropped_multi and any(a.variable_name == k for a in attrs)
    }

    # Multi-target intent queue drain: every change-request entry point
    # converges here. Clear the just-applied attr from the queue, then
    # force the queue head to pending_variables[0] (outranks catalog /
    # hardware ordering) so the next turn asks for its value. Not excluded
    # for already being in session.filled — change targets are normally
    # already filled.
    clear_queue_vn(session, changed_attr.variable_name)
    pending = drain_intent_queue_into_pending(session, pending, visible_attrs)

    user_value_overridden, requested_display, pending = _revert_overridden_user_value(
        session, changed_attr, result, pending,
    )

    return (
        visible_attrs, filled, display_filled, constrained_opts, pending,
        rule_ids, bml_eval, dropped_multi, user_value_overridden, requested_display,
    )
