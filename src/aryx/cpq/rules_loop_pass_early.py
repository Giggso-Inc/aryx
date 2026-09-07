"""First half of ``evaluate_rules_loop``'s per-pass body (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): hidden-master-string
refresh, hiding rules, ungoverned-attr suppression, and auto_fill
itself. Logic unchanged from the original inline pass. The second half
(recommendation/constraint rules, the break check) is
`rules_loop_pass_late.py`.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.cpq import rule_trace
from aryx.cpq.engine import _DECISION_ANCHOR_VNS, logger
from aryx.cpq.rules_loop_pass_autofill import run_autofill_step
from aryx.cpq.rules_loop_state import LoopScope, LoopState


def run_early_pass(engine: Any, pass_num: int, state: LoopState, scope: LoopScope) -> None:
    """Mutates `state` in place through the hide -> auto-fill half of
    one pass. Populates `state.prev_filled_keys`/`prev_visible_ids`
    (read by `rules_loop_pass_late.run_late_pass`'s break check) and
    `state.inconsistent_vns`.
    """
    state.pass_t0 = time.monotonic()
    rule_trace.bind_pass(pass_num)
    state.prev_filled_keys = set(state.filled.keys())
    state.prev_visible_ids = {a.entity_id for a in state.attrs}

    # Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): warm the
    # shared Tier-2 cache CONCURRENTLY for every hiding rule's script
    # before apply_hiding_rules runs its own sequential loop below --
    # live-measured on the real CommandCentral Aware catalog, 823
    # distinct hiding-rule scripts needed Tier-2 in a single turn;
    # evaluated one at a time that took 25+ minutes. apply_hiding_rules
    # itself is UNCHANGED -- it still calls bml_eval.hide_for_script(...)
    # per rule in order; every one of those calls now just hits the
    # cache this just populated, instead of making a fresh network call.
    # A rule this prefetch missed simply falls through to its normal
    # sequential call, exactly as if this line didn't exist.
    if scope.bml_eval is not None:
        scope.bml_eval.prefetch_tier2(
            engine._bml_prefetch_requests(hiding=scope.hiding_rules, filled=state.filled))

    # docs/CPQ_HIDDEN_MASTER_STRING_HIDING_RULE_GAP_PLAN_2026_08_10.md --
    # populate the one shared variable dozens of hiding-rule scripts
    # check membership in, via the real ingested attrSequence Data
    # Table, before apply_hiding_rules runs those scripts below.
    #
    # docs/CPQ_HIDDEN_MASTER_STRING_STALE_AFTER_CASCADE_PLAN_2026_08_
    # 10.md -- recompute whenever the two real inputs this value is
    # derived from (product, base model) have changed since the cached
    # value was computed, not just when the key is merely absent.
    # Confirmed live: a mid-conversation Hardware Version change
    # cascades productSelectionProduct_all to a new value, but the
    # master string cached for the OLD product persisted -- every
    # hiding rule keyed on it then evaluated against the wrong
    # product's data. Tracking key kept as a plain string (not a
    # tuple) -- `filled` round-trips through JSON between turns, and a
    # tuple would silently become a list on deserialization, breaking
    # the equality check on the very next turn.
    _hidden_ms_key = (
        state.filled.get("productSelectionProduct_all", "") + "\x1f"
        + state.filled.get("modelSelectionbaseModel_astro", "")
    )
    if (
        "hiddenMasterStringForAstroPortable_astro" not in state.filled
        or state.filled.get("_hiddenMasterStringForAstroPortable_astro_computed_for")
        != _hidden_ms_key
    ):
        _hidden_ms = engine._compute_hidden_master_string(
            state.filled, scope.workspace_id, scope.catalog_prefix, state.dt_cache,
            attrs=state.attrs,
        )
        if _hidden_ms is not None:
            state.filled["hiddenMasterStringForAstroPortable_astro"] = _hidden_ms
            state.filled["_hiddenMasterStringForAstroPortable_astro_computed_for"] = _hidden_ms_key

    # Apply hiding rules first so auto_fill only fills visible attrs
    state.attrs, _msgs, hidden_vns = engine.apply_hiding_rules(
        state.attrs, state.filled, scope.hiding_rules,
        bml_eval=scope.bml_eval, filled_multi=state.multi)

    # docs/CPQ_HIDDEN_VALUE_TEMPORARY_VS_CONFIRMED_PLAN_2026_08_16.md --
    # strip filled/multi for `hidden_vns` UNLESS a core decision anchor
    # (Product, Base Model, Hardware Version, Country) is still
    # unanswered. That's the one narrow window where a hide is merely
    # gating rather than a real invalidation -- once every anchor IS
    # answered, a hide almost always means a REAL, current-state
    # conflict, and leaving those stale values in `filled`/`multi` let
    # them keep colliding with new answers turn after turn.
    if all(
        state.filled.get(_anchor_vn) for _anchor_vn in _DECISION_ANCHOR_VNS
    ):
        for k in hidden_vns:
            state.filled.pop(k, None)
            state.display_filled.pop(k, None)
            state.sources.pop(k, None)
            state.multi.pop(k, None)

    # Real Oracle CPQ attrSequence Data Table narrowing -- an attr
    # confidently NOT part of the active base model per real ingested
    # data is suppressed the same way an explicit hiding rule removes
    # one from view. `None`/no workspace_id is a no-op.
    _t0 = time.monotonic()
    state.attrs, suppressed_vns = engine._suppress_ungoverned_attrs(
        state.attrs, state.filled, scope.workspace_id, scope.catalog_prefix, state.dt_cache,
    )
    logger.info(
        "cpq_perf: _suppress_ungoverned_attrs took %.3fs pass=%d attrs=%d suppressed=%d",
        time.monotonic() - _t0, pass_num, len(state.attrs), len(suppressed_vns),
    )
    for k in suppressed_vns:
        state.filled.pop(k, None)
        state.display_filled.pop(k, None)
        state.sources.pop(k, None)
        state.multi.pop(k, None)

    run_autofill_step(engine, pass_num, state, scope)
