"""``evaluate_rules_loop`` (Phase 4, one of the 8 previously-deferred
oversized `CpqEngine` methods, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). Orchestrates the fixed-point hide -> auto-fill ->
recommend -> constrain loop; the actual per-pass work lives in
`rules_loop_pass_early.py`/`rules_loop_pass_late.py`, threaded through
`rules_loop_state.py`'s `LoopState`/`LoopScope`.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.config import get_settings
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.engine import logger
from aryx.cpq.rules_loop.full_attrs_registry import remember_full_attrs, remember_rule_hidden
from aryx.cpq.rule_trace import rule_trace
from aryx.raven_log import raven_log, would_log
from aryx.cpq.rules_loop.rules_loop_pass_early import run_early_pass
from aryx.cpq.rules_loop.rules_loop_pass_late import run_late_pass
from aryx.cpq.rules_loop.rules_loop_state import LoopScope, LoopState
from aryx.cpq.rules_loop.rules_loop_timing import totals_line

_MAX_LOOPS = 8


def evaluate_rules_loop(
    engine: Any,
    attrs: list[Any],
    hints: dict[str, str],
    filled: dict[str, str],
    hiding_rules: list[Any],
    rec_rules: list[Any],
    con_rules: list[Any],
    bml_eval: Any | None = None,
    filled_source: dict[str, str] | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    dropped_multi: dict[str, list[str]] | None = None,
    country: str | None = None,
    negated_vns: set[str] | None = None,
    skip_always_ask: set[str] | None = None,
    rule_conflict_order: dict[str, int] | None = None,
    display_order: dict[str, int] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    product_anchor_hint: str | None = None,
    _dt_cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[list[Any], dict[str, str], dict[str, str], dict[int, list[str]]]:
    """Run hide → recommend → constrain → auto-fill until state is stable.

    workspace_id/catalog_prefix — passed straight through to auto_fill's
    real-Data-Table fallback; `None` (the default) keeps every existing
    caller's behavior unchanged.

    product_anchor_hint — the customer's own original wording (see
    CpqSession.product_anchor_question), passed straight through to
    every internal `auto_fill` call's own Hardware-Version-not-
    applicable override (see that param's own docstring there);
    `None` (the default) keeps every existing caller's behavior
    unchanged.

    display_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2d:
    passed straight through to every internal `auto_fill` call so the
    default-value/first-available skip gate applies on EVERY pass, not
    just the caller's own separate, final `auto_fill` call in
    ask_api.py. Without this, an attr could get a "default"-sourced
    value locked in during this loop's own early passes -- that value
    then looks like "already filled in a prior turn" to every later
    pass (which only re-validates against constraints, never re-
    derives from scratch), so the §2d skip never gets a chance to
    apply. Confirmed live: exactly this happened for 8 real attrs
    before this fix.

    rule_conflict_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md
    §2b: the catalog's FULL layout document order
    (`_load_layout_full_order`), passed straight through to
    `rank_rules_by_specificity`. `None` keeps today's dependency-
    graph-depth ranking unchanged.

    Each pass: (1) auto-fill (hints + defaults + first-option, with
    active constraints), (2) apply hiding rules -> update visible
    attrs, (3) apply recommendation rules -> add new auto-fills, (4)
    apply constraint rules -> update constrained option sets. Iterates
    until neither the filled set nor the visible attr set changes.
    filled_source/filled_multi are updated in place when supplied.
    Returns (visible_attrs, filled, display_filled, constrained_opts).

    skip_always_ask — passed straight through to auto_fill; compute via
    resolve_always_ask_skips() once per turn at the caller.

    _dt_cache — optional caller-owned Data Table cache (same shape as
    auto_fill's `_dt_cache`) so a later standalone auto_fill can reuse the
    loop's memoized table scans. None keeps prior behavior.
    """
    sources = filled_source if filled_source is not None else {}
    multi = filled_multi if filled_multi is not None else {}
    dropped = dropped_multi if dropped_multi is not None else {}

    # docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md --
    # ranked ONCE here against the full, pre-loop `attrs` (never the
    # loop-local `attrs`, which apply_hiding_rules reassigns to a
    # shrinking subset every pass) so same-target hiding/recommendation
    # conflicts resolve via provable specificity instead of whatever
    # order fetch_rules()/fetch_value_rules() happened to return.
    hiding_rules, rec_rules, con_rules = engine.rank_rules_by_specificity(
        attrs, hiding_rules, rec_rules, con_rules, display_order=rule_conflict_order)

    state = LoopState(
        attrs=attrs, filled=filled, display_filled={}, sources=sources,
        multi=multi, dropped=dropped, dt_cache=_dt_cache or {},
    )
    state.dt_cache[("_all_attrs", workspace_id, catalog_prefix)] = attrs     # the full list, for the required set's rule inputs
    if getattr(get_settings(), "cpq_required_set_rules_read_all_attrs_enabled", False) is True:
        remember_full_attrs(workspace_id, catalog_prefix, attrs)              # for callers with their own turn cache
    scope = LoopScope(
        hints=hints, hiding_rules=hiding_rules, rec_rules=rec_rules,
        con_rules=con_rules, bml_eval=bml_eval, country=country,
        negated_vns=negated_vns, skip_always_ask=skip_always_ask,
        display_order=display_order, workspace_id=workspace_id,
        catalog_prefix=catalog_prefix, product_anchor_hint=product_anchor_hint,
    )

    # cpq_step start/done -- the per-pass "cpq_perf: pass N total ...s"
    # lines already cover per-pass granularity; this brackets the WHOLE
    # fixed-point loop (all up to _MAX_LOOPS=8 passes) so a hang
    # anywhere inside shows up as "start" with no matching "done" for
    # this run_id, rather than only inferring it from a missing pass log.
    _loop_t0 = time.monotonic()
    logger.info("cpq_step: evaluate_rules_loop start max_passes=%d", _MAX_LOOPS)
    # pass_num pre-seeded defensively -- the "done" log below reads it
    # after the loop, which is only safe today because _MAX_LOOPS is a
    # positive constant guaranteeing at least one iteration.
    pass_num = -1
    should_break = False
    fill_log.bind_sources(sources)
    for pass_num in range(_MAX_LOOPS):
        fill_log.set_pass(pass_num)
        run_early_pass(engine, pass_num, state, scope)
        should_break = run_late_pass(engine, pass_num, state, scope)
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.rules_loop.pass pass finished", context={
                "pass": pass_num, "filled_count": len(state.filled), "visible_attr_count": len(state.attrs),
                "multi_count": len(state.multi), "constrained_attr_count": len(state.constrained_opts or {}),
                "resynced_count": len(getattr(state, "resynced", None) or {}),
                "inconsistent_count": len(state.inconsistent_vns),
                "oscillating_count": len(state.oscillating_vns), "stable": should_break,
                "rules_hiding": len(scope.hiding_rules), "rules_rec": len(scope.rec_rules),
                "rules_con": len(scope.con_rules)})
        if should_break:
            break
    fill_log.set_pass(None)
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.rules_loop.stopped loop exit", context={
            "selected_option": "converged" if should_break else "max_passes",
            "available_options": ["converged", "max_passes"],
            "reason_code": "STATE_STABLE" if should_break else "MAX_PASSES_REACHED",
            "policy_version": "rules_loop_v1", "passes": pass_num + 1, "max_passes": _MAX_LOOPS})

    logger.info(
        "cpq_step: evaluate_rules_loop done elapsed_s=%.3f passes=%d",
        time.monotonic() - _loop_t0, pass_num + 1,
    )
    
    # one line per turn: cumulative seconds per stage, largest first ("where did the minutes go")
    logger.info(totals_line(state, time.monotonic() - _loop_t0, pass_num + 1))
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.rules_loop.timing per-stage totals for the turn", context={
            "passes": pass_num + 1, "total_ms": int((time.monotonic() - _loop_t0) * 1000),
            "stage_ms": {name: int(seconds * 1000) for name, seconds in state.stage_s.items()}})
    # Durably flush this turn's buffered rule-trace fires in one round
    # trip (see rule_trace.py's record_fire/_flush_batch_size()) so the
    # trace is fully durable by the time this turn's response returns,
    # even though individual fires are no longer written one at a time.
    rule_trace.flush_pending()
    _remember_rule_hidden(attrs, state.attrs, workspace_id, catalog_prefix)
    return _scoped_attrs(engine, state, scope), state.filled, state.display_filled, state.constrained_opts


def _remember_rule_hidden(attrs: list, visible: list, workspace_id: int | None, catalog_prefix: str) -> None:
    """Flag `cpq_beautify_hide_rule_hidden_enabled`: record the attributes the hiding rules removed (in the loop's input,
    not hidden by the catalog itself, not in the final visible list) for Beautify. Taken before the model scoping in
    `_scoped_attrs`, which drops attributes for another reason."""
    if getattr(get_settings(), "cpq_beautify_hide_rule_hidden_enabled", False) is not True:
        return
    shown = {a.variable_name for a in visible}
    remember_rule_hidden(workspace_id, catalog_prefix,
                         {a.variable_name for a in attrs if not getattr(a, "hidden", False) and a.variable_name not in shown})


def _scoped_attrs(engine: Any, state: LoopState, scope: LoopScope) -> list:
    """The turn's attribute list for the completeness checks, scoped like the loop's own passes (flag
    `cpq_model_scoped_questions_enabled`). The passes drop an attribute the model's sequence rows do not list, but the
    visible list is rebuilt from the whole catalog each pass, so the returned list still held them and the
    'missing required data' check counted another family's required attributes. A value a rule or a guess left on a dropped
    attribute is removed with it. Off: nothing changes."""
    from aryx.cpq.model_scoping_flags import scoped_questions_enabled  # noqa: PLC0415 -- flag-gated

    if not scoped_questions_enabled():
        return state.attrs
    try:
        kept, suppressed = engine._suppress_ungoverned_attrs(
            state.attrs, state.filled, scope.workspace_id, scope.catalog_prefix, state.dt_cache, state.sources,
        )
        for vn in suppressed:       # same as the early pass: an attribute out of the list holds no value either
            state.filled.pop(vn, None)
            state.display_filled.pop(vn, None)
            state.sources.pop(vn, None)
            state.multi.pop(vn, None)
        return kept
    except Exception:  # noqa: BLE001 -- scoping must never break a turn
        logger.debug("cpq: scoped attribute list failed; returning the unscoped list", exc_info=True)
        return state.attrs

