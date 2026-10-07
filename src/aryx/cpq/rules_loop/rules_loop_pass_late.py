"""Second half of ``evaluate_rules_loop``'s per-pass body (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): recommendation/
constraint rule application and the fixed-point break check. Logic
unchanged from the original inline pass. The first half (hiding rules,
auto_fill) is `rules_loop_pass_early.py`.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.config import get_settings
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.engine import logger
from aryx.raven_log import raven_log, would_log
from aryx.cpq.rules_loop.rules_loop_state import LoopScope, LoopState
from aryx.cpq.rules_loop.rules_loop_timing import add_stage, stage_done


def _whitelist_narrow_kwargs() -> dict[str, bool]:
    """``narrow_from_data_tables=True`` only when
    cpq_whitelist_narrow_questions_enabled is on; otherwise no extra kwarg
    (the call is then byte-identical to before)."""
    if get_settings().cpq_whitelist_narrow_questions_enabled:
        return {"narrow_from_data_tables": True}
    return {}


def run_late_pass(engine: Any, pass_num: int, state: LoopState, scope: LoopScope) -> bool:
    """Mutates `state` in place through the recommend -> constrain half
    of one pass. Returns True when the fixed-point loop should break
    (nothing new changed this pass).
    """
    # Same prefetch, now for recommendation/constraint rule scripts
    # against the POST-auto_fill state (auto_fill can itself have just
    # resolved values these scripts depend on) -- warms the cache for
    # apply_recommendation_rules/apply_constraint_rules below, both
    # still unchanged, still sequential, now cache hits.
    if scope.bml_eval is not None:
        _t0 = time.monotonic()
        scope.bml_eval.prefetch_tier2(engine._bml_prefetch_requests(
            attrs=state.attrs, rec=scope.rec_rules, con=scope.con_rules, filled=state.filled))
        logger.info(
            "cpq_perf: prefetch_tier2 (post-auto_fill) took %.3fs pass=%d",
            time.monotonic() - _t0, pass_num,
        )
        add_stage(state, "prefetch_tier2_post_autofill", _t0)

    _t0 = time.monotonic()
    new_fills = engine.apply_recommendation_rules(
        state.attrs, state.filled, scope.rec_rules, bml_eval=scope.bml_eval,
        filled_multi=state.multi, constrained_opts=state.constrained_opts,
        workspace_id=scope.workspace_id, catalog_prefix=scope.catalog_prefix, dt_cache=state.dt_cache,
    )
    logger.info(
        "cpq_perf: apply_recommendation_rules took %.3fs pass=%d",
        time.monotonic() - _t0, pass_num,
    )
    add_stage(state, "apply_recommendation_rules", _t0)
    if new_fills:
        # Route multi-select targets to `multi`, not `filled` -- same
        # reasoning as auto_fill's final assignment block: this is yet
        # another path that can hand a value to a select_type=="multi"
        # attr, and build_payload only serializes an attr's value as an
        # array when it's stored in filled_multi.
        by_vn_for_type = {a.variable_name: a for a in state.attrs}
        for k, (iv, d) in new_fills.items():
            tgt = by_vn_for_type.get(k)
            fill_log.log_write_dicts(
                state.filled, state.multi, state.sources, tgt, k,
                [iv] if tgt is not None and tgt.select_type == "multi" else iv, d, "rule",
                "apply_recommendation_rules", multi=tgt is not None and tgt.select_type == "multi", force=True)
            if tgt is not None and tgt.select_type == "multi":
                state.multi[k] = [iv]
            else:
                state.filled[k] = iv
            state.display_filled[k] = d
            # Force-set, not setdefault: `k` only ever reaches here via
            # the truthy (not `in filled`) check above, so any existing
            # tag is either absent or D4's empty-value "user"-cleared
            # marker being genuinely overridden by a real rule firing --
            # never a real prior value's tag.
            state.sources[k] = "rule"

    # docs/config_consistency_issues_2026-07-30.md issue 6 (FedRAMP) --
    # a recommendation-governed attr the ENGINE already filled (never
    # the customer's own choice) must not be permanently locked in if
    # its driving attribute's value changes on a LATER pass of this
    # same loop.
    _t0 = time.monotonic()
    resynced = engine.resync_stale_recommendations(
        state.attrs, state.filled, state.sources, scope.rec_rules,
        bml_eval=scope.bml_eval, filled_multi=state.multi,
        constrained_opts=state.constrained_opts,
    )
    state.resynced = resynced
    logger.info(
        "cpq_perf: resync_stale_recommendations took %.3fs pass=%d",
        time.monotonic() - _t0, pass_num,
    )
    add_stage(state, "resync_stale_recommendations", _t0)
    # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md (RC4,
    # 2026-08-24; refined RC5, 2026-08-24): live-confirmed a SECOND,
    # structurally identical churn source to RC3's paired-value
    # invalidation -- resync_stale_recommendations can permanently
    # disagree with whatever auto_fill just derived, mutating `filled`
    # every single pass. Same containment as RC3, same RC5
    # intersection refinement, tracked independently of the paired-
    # value source so an attr alternating between the two mechanisms
    # is still caught.
    _frozen_resynced = frozenset(resynced.keys()) if resynced else frozenset()
    state.oscillating_vns |= (_frozen_resynced & state.last_resync_vns)
    state.last_resync_vns = _frozen_resynced
    if resynced:
        for k, (iv, d) in resynced.items():
            fill_log.log_write_dicts(state.filled, state.multi, state.sources, None, k, iv, d, "rule",
                                     "resync_stale_recommendations", force=True)
            state.filled[k] = iv
            state.display_filled[k] = d
            state.sources[k] = "rule"

    _t0 = time.monotonic()
    state.constrained_opts = engine.apply_constraint_rules(
        state.attrs, scope.con_rules, state.filled, bml_eval=scope.bml_eval,
        filled_multi=state.multi, workspace_id=scope.workspace_id,
        catalog_prefix=scope.catalog_prefix, _dt_cache=state.dt_cache,
        _constraint_cache=state.constraint_cache,
        _signature_exclude_vns=frozenset(state.oscillating_vns),
        narrowing_rec_rules=scope.rec_rules,
        **_whitelist_narrow_kwargs(),
    )
    logger.info(
        "cpq_perf: apply_constraint_rules (in-loop) took %.3fs pass=%d",
        time.monotonic() - _t0, pass_num,
    )
    add_stage(state, "apply_constraint_rules", _t0)
    _t0 = time.monotonic()
    engine._apply_series_mapping_exclusions(
        state.attrs, state.constrained_opts, state.filled,
        scope.workspace_id, scope.catalog_prefix, state.dt_cache,
    )
    logger.info(
        "cpq_perf: _apply_series_mapping_exclusions took %.3fs pass=%d",
        time.monotonic() - _t0, pass_num,
    )
    add_stage(state, "series_mapping_exclusions", _t0)

    logger.info(
        "cpq_perf: pass %d total %.3fs resynced=%s inconsistent=%d",
        pass_num, time.monotonic() - state.pass_t0, bool(resynced), len(state.inconsistent_vns),
    )
    # 2026-08-28 perf fix: this break was gated on RAW resynced/
    # inconsistent_vns, so a single already-proven-non-convergent vn
    # (tracked in oscillating_vns precisely so its churn stops
    # perturbing everything else) silently defeated this exit on
    # EVERY real turn -- confirmed live: every sampled turn ran the
    # full 8 passes, never fewer. Excluding oscillating_vns members
    # from both checks lets the loop exit once nothing NEW is
    # churning, while a genuinely still-narrowing vn still correctly
    # blocks the break.
    non_oscillating_resynced = (
        (frozenset(resynced.keys()) if resynced else frozenset())
        - state.oscillating_vns
    )
    non_oscillating_inconsistent = frozenset(state.inconsistent_vns) - state.oscillating_vns
    _stable = bool(
        not non_oscillating_resynced
        and not non_oscillating_inconsistent
        and set(state.filled.keys()) == state.prev_filled_keys
        and {a.entity_id for a in state.attrs} == state.prev_visible_ids
    )
    if would_log("DEBUG"):
        _keys_same = set(state.filled.keys()) == state.prev_filled_keys
        _vis_same = {a.entity_id for a in state.attrs} == state.prev_visible_ids
        raven_log("DEBUG", "P4", "ask.rules_loop.break_check stability check", context={
            "selected_option": "stop" if _stable else "continue", "available_options": ["stop", "continue"],
            "reason_code": "STABLE" if _stable else "STATE_CHANGED", "policy_version": "rules_loop_v1",
            "pass": pass_num, "resynced_non_oscillating": len(non_oscillating_resynced),
            "inconsistent_non_oscillating": len(non_oscillating_inconsistent),
            "filled_keys_unchanged": _keys_same, "visible_unchanged": _vis_same})
    return _stable
