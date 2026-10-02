"""Re-running the hide->recommend->constrain->auto-fill loop after an
optional attribute is re-activated, split out of `_handle_attr_
activation` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling `ask_handle_
attr_activation.py` under the line cap. Logic unchanged from the
original inline block, INCLUDING a pre-existing bug: `_grid_qty_vns`
below is referenced but never defined anywhere in this codebase (grep
confirms no other definition) — a NameError whenever `activated_vn in
filled` and its source isn't "rule"/"country_derived" at the same time.
Preserved verbatim rather than silently fixed, since fixing an
unverified behavior change is out of scope for a pure code-move.
`_cpq_engine` is read through the ask_api MODULE object (not imported by
name) since at least one test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_scope_and_pending.ask_pending_exclusion import _hard_exclude_from_pending
from aryx.api.ask_scope_and_pending.ask_singleton_pending import _auto_resolve_singleton_pending
from aryx.cpq.grid_quantity.narrow import grid_narrow_kwargs


def _recompute_after_attr_activation(
    req: "Any", session: Any, attrs: list, activated_vn: str,
    hiding_rules: list, rec_rules: list, con_rules: list,
) -> tuple:
    """Rebuilds hints from the customer's message, re-runs the full
    hide->recommend->constrain->auto-fill loop, un-guesses a blind fill on
    the just-activated attr (D2 §4.3 "never silently guesses"), reconciles
    session state, then applies the same hard-exclude/singleton-pending
    narrowing every other cascade handler applies. Returns (pending,
    visible_attrs, filled, display_filled, constrained_opts, rule_ids,
    bml_eval, catalog_prefix).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
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

    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
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

    if (activated_vn in filled
            and session.filled_source.get(activated_vn) not in ("rule", "country_derived")
            and activated_vn not in _grid_qty_vns):  # noqa: F821 -- pre-existing bug, see module docstring
        filled.pop(activated_vn, None)
        display_filled.pop(activated_vn, None)
        _act_attr_resolved = next(
            (a for a in visible_attrs if a.variable_name == activated_vn), None)
        if _act_attr_resolved is not None:
            pending.insert(0, _act_attr_resolved)

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

    pending = _hard_exclude_from_pending(
        pending, filled, display_filled, session.filled_source,
        con_rules, bml_eval, rec_rules=rec_rules,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
        all_attrs=attrs,
    )
    pending = _auto_resolve_singleton_pending(
        pending, filled, display_filled, session.filled_source,
        con_rules, bml_eval, workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
    )
    return (
        pending, visible_attrs, filled, display_filled, constrained_opts,
        rule_ids, bml_eval, catalog_prefix,
    )
