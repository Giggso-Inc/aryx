"""``run_early_pass``'s auto_fill sub-step (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md) -- split off purely to keep
`rules_loop_pass_early.py` under the file-size cap. Logic unchanged.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.cpq.engine import logger
from aryx.cpq.rules_loop.rules_loop_state import LoopScope, LoopState
from aryx.cpq.rules_loop.rules_loop_timing import add_stage, stage_done


def run_autofill_step(engine: Any, pass_num: int, state: LoopState, scope: LoopScope) -> None:
    """Mutates `state` in place: governed_ids/rule_ids computation,
    auto_fill itself, and the paired-value consistency invalidation
    right after it. Populates `state.inconsistent_vns`.
    """
    _t0 = time.monotonic()
    governed_ids = engine.governed_target_ids(
        state.attrs, scope.hiding_rules, scope.rec_rules, scope.con_rules)
    rule_ids = engine.rule_governed_ids(
        state.attrs, scope.hiding_rules, scope.rec_rules, scope.con_rules)
    stage_done(state, "governed_ids", _t0, pass_num)

    # docs/CPQ_AUTO_FILL_TIER2_PREFETCH_GAP_PLAN_2026_08_10.md -- auto_
    # fill's own _satisfied_recommendation helper calls bml_eval.
    # allowed_values_for_script/condition_holds per (unfilled attr,
    # targeting recommendation rule) pair -- the same Tier-1/Tier-2
    # machinery apply_recommendation_rules uses, but BEFORE the
    # prefetch in the late pass (which only warms the cache for
    # apply_recommendation_rules/apply_constraint_rules' own later
    # calls). Confirmed live: on pass 0, this uncovered gap made
    # auto_fill itself take 20-21s of serial Tier-2 network round-
    # trips. Warming against the PRE-auto_fill filled state here is
    # safe and non-wasteful even though the same rules get prefetched
    # again in the late pass against the POST-auto_fill state --
    # prefetch_tier2 dedupes and caches by (script, variables).
    if scope.bml_eval is not None:
        _t0 = time.monotonic()
        scope.bml_eval.prefetch_tier2(engine._bml_prefetch_requests(
            attrs=state.attrs, rec=scope.rec_rules, filled=state.filled))
        stage_done(state, "prefetch_tier2_autofill", _t0, pass_num)

    _t0 = time.monotonic()
    state.filled, state.display_filled, _ = engine.auto_fill(
        state.attrs, scope.hints, already_filled=state.filled,
        constrained_opts=state.constrained_opts,
        filled_source=state.sources, governed_ids=governed_ids,
        already_filled_multi=state.multi, dropped_multi=state.dropped,
        rule_governed_ids=rule_ids, country=scope.country, rec_rules=scope.rec_rules,
        negated_vns=scope.negated_vns, skip_always_ask=scope.skip_always_ask,
        bml_eval=scope.bml_eval, display_order=scope.display_order,
        workspace_id=scope.workspace_id, catalog_prefix=scope.catalog_prefix,
        _dt_cache=state.dt_cache, hiding_rules=scope.hiding_rules,
        _default_fill_signatures=state.default_fill_signatures,
        _signature_exclude_vns=frozenset(state.oscillating_vns),
        product_anchor_hint=scope.product_anchor_hint,
    )
    logger.info(
        "cpq_perf: auto_fill took %.3fs pass=%d", time.monotonic() - _t0, pass_num,
    )
    add_stage(state, "auto_fill", _t0)

    # Real Data Table pair-consistency check -- two attributes auto_
    # fill resolved INDEPENDENTLY can each be individually legal while
    # their combination is one the real catalog never allows. Clearing
    # both lets the next pass re-resolve them together instead of
    # leaving a structurally-invalid combination locked into the
    # payload.
    _t0 = time.monotonic()
    state.inconsistent_vns = engine._invalidate_inconsistent_paired_values(
        state.filled, state.sources, scope.workspace_id, scope.catalog_prefix, state.dt_cache,
    )
    logger.info(
        "cpq_perf: _invalidate_inconsistent_paired_values took %.3fs pass=%d inconsistent=%s",
        time.monotonic() - _t0, pass_num, sorted(state.inconsistent_vns),
    )
    add_stage(state, "invalidate_inconsistent_paired_values", _t0)
    # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md (RC3,
    # 2026-08-24; refined RC5, 2026-08-24): any vn present in this
    # pass's AND the immediately preceding pass's invalidated set is
    # proof of non-convergent churn for THAT vn specifically, not a
    # real narrowing in progress -- fold the INTERSECTION (not exact
    # set equality) into oscillating_vns. Live-confirmed exact-equality
    # was too strict: a genuinely persistent churner never got caught
    # when a second, unrelated vn sporadically joined/left the set
    # pass to pass. Intersection catches the persistent core while a
    # vn that stops appearing (real convergence) is correctly dropped.
    _frozen_inconsistent = frozenset(state.inconsistent_vns)
    state.oscillating_vns |= (_frozen_inconsistent & state.last_inconsistent_vns)
    state.last_inconsistent_vns = _frozen_inconsistent
    for k in state.inconsistent_vns:
        state.filled.pop(k, None)
        state.display_filled.pop(k, None)
        state.sources.pop(k, None)
        state.multi.pop(k, None)
