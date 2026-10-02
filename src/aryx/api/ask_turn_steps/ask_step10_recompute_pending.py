"""One evaluate_rules_loop + auto_fill + post-filter pass, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Originally a nested
closure (`_recompute_pending`) local to STEP 3, capturing `attrs`,
`session`, the rule sets, `bml_eval`, `dropped_multi`, `negated_vns`,
`skip_always_ask`, `validation_rules`, `req`, and `catalog_prefix` from
the enclosing scope — factored so Amendment 17 can re-run the exact
same pass a second time after enriching `hints` with LLM-extracted
facts, without duplicating this block or risking it drift out of sync
with the normal (Tier-1-only) path. Rewritten to take every captured
name as an explicit parameter (same treatment as `_complete_product_
switch` in Phase 10 step 1) so it can be called from outside the
enclosing function. Logic unchanged from the original inline
definition. `_cpq_engine` is read through the ask_api module object
(not imported by name) since at least one test replaces the whole
singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.grid_quantity.narrow import grid_narrow_kwargs



def _step10_recompute_pending(
    cur_hints: dict, attrs: list, session: Any, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, dropped_multi: dict, negated_vns: set,
    skip_always_ask: set, validation_rules: list, req: "Any", catalog_prefix: str,
) -> "tuple[list, dict, dict, list, dict, set]":
    """Returns (visible_attrs, filled, display_filled, pending,
    constrained_opts, rule_ids)."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine

    v_attrs, f, d_filled, c_opts = _cpq_engine.evaluate_rules_loop(
        attrs, cur_hints, dict(session.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=session.filled_source,
        filled_multi=session.filled_multi, dropped_multi=dropped_multi,
        country=session.country, negated_vns=negated_vns,
        skip_always_ask=skip_always_ask,
        rule_conflict_order=_cpq_engine._load_layout_full_order(req.workspace_id, catalog_prefix),
        display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
    )
    g_ids = _cpq_engine.governed_target_ids(v_attrs, hiding_rules, rec_rules, con_rules)
    r_ids = _cpq_engine.rule_governed_ids(v_attrs, hiding_rules, rec_rules, con_rules)
    f, d_filled, p = _cpq_engine.auto_fill(
        v_attrs, cur_hints, already_filled=f, constrained_opts=c_opts,
        governed_ids=g_ids, already_filled_multi=session.filled_multi,
        dropped_multi=dropped_multi, rule_governed_ids=r_ids, country=session.country,
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
        # "pending" with nothing to fall back to. Since the resolved
        # model-leaf identity already proves these "Product"-labeled attrs
        # are irrelevant to THIS catalog's real flow (Amendment 5 Finding
        # 3), drop them from `pending` outright rather than asking for
        # them at all — they're already excluded from the payload above.
        p = [
            a for a in p
            if a.variable_name not in _cpq_engine.product_label_noise_vns(
                v_attrs, hiding_rules, rec_rules, con_rules)
        ]
    p = _cpq_engine.append_pending_grid_quantities(
        p, v_attrs, f, session.filled_multi, session.filled_source, c_opts,
        **grid_narrow_kwargs(req.workspace_id, catalog_prefix))
    return v_attrs, f, d_filled, p, c_opts, r_ids
