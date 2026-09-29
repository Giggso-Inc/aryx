"""Exclusive-sibling-family enforcement and the Amendment 17 multi-attr
LLM hint re-run, split out of `_run_cpq_turn_inner` (Phase 10/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Issue 5 (docs/config_consistency_issues_2026-07-30.md): two attrs
sharing the same real-world concept (near-identical label, one
single-select one multi-select) can both end up filled in the same
turn when no catalog hiding rule actually excludes either for the
current product — strip the weakly-sourced single-select sibling and
ask for the multi-select one instead. Amendment 17: Tier-1's fragment
matching can deliberately leave 2+ attrs unresolved on one dense
sentence — give the shared Tier-2 classifier one shot at the ones this
sentence genuinely seems to mention (GENUINE multi-mention overlap
only) before falling back to asking one at a time. Logic unchanged from
the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_llm.ask_llm_extract_multi_attr_hints import _llm_extract_multi_attr_hints
from aryx.api.ask_catalog.ask_relevant_intent_candidates import _relevant_intent_candidates
from aryx.api.ask_turn_steps.ask_step10_recompute_pending import _step10_recompute_pending



def _step10_enforce_siblings_and_multi_hint(
    req: "Any", session: Any, attrs: list, hints: dict, visible_attrs: list,
    filled: dict, display_filled: dict, pending: list, constrained_opts: dict,
    rule_ids: set, rec_rules: list, con_rules: list, hiding_rules: list, bml_eval: Any,
    dropped_multi: dict, negated_vns: set, skip_always_ask: set, validation_rules: list,
    catalog_prefix: str,
) -> "tuple[list, dict, dict, list, dict, set]":
    """Returns the (possibly updated) (visible_attrs, filled,
    display_filled, pending, constrained_opts, rule_ids) tuple."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine

    _sibling_catalog_confirmed_vns = (
        _cpq_engine._rule_forced_from_active_decision_vns(
            [*rec_rules, *con_rules], visible_attrs, session.filled_source,
            _cpq_engine._CONFIG_DATA_ACTIVE_SOURCES,
        )
        | _cpq_engine._data_table_forced_vns(
            filled, req.workspace_id, catalog_prefix, filled_multi=session.filled_multi,
        )
    )
    pending = _cpq_engine.enforce_exclusive_sibling_families(
        visible_attrs, filled, session.filled_multi, session.filled_source,
        display_filled, pending, all_attrs=attrs,
        catalog_confirmed_vns=_sibling_catalog_confirmed_vns,
        product_name=session.product_name, workspace_id=req.workspace_id,
        catalog_prefix=catalog_prefix,
    )

    if len(pending) >= 2:
        _multi_candidates = _relevant_intent_candidates(
            req.question, pending, fallback_to_full=False)
        if len(_multi_candidates) >= 2:
            _extra_hints = _llm_extract_multi_attr_hints(
                req.question, _multi_candidates, req.workspace_id)
            if _extra_hints:
                for _vn, _iv in _extra_hints.items():
                    hints.setdefault(_vn, _iv)
                visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids = (
                    _step10_recompute_pending(
                        hints, attrs, session, hiding_rules, rec_rules, con_rules,
                        bml_eval, dropped_multi, negated_vns, skip_always_ask,
                        validation_rules, req, catalog_prefix,
                    ))
    return visible_attrs, filled, display_filled, pending, constrained_opts, rule_ids
