"""``apply_constraint_rules`` (Phase 4, one of the 8 previously-deferred
oversized `CpqEngine` methods, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). Orchestrates: cache check, the main rule-application
loop (`constraint_rules_apply.py`), the empty-intersection fallback
(`constraint_rules_fallback.py`), and the narrowing_rec_rules pass
(`constraint_rules_narrowing.py`).

`_fill_signature` is looked up through the engine MODULE (not imported
by name) because tests/test_cpq_rule_loop_perf_gating_2026_08_19.py
monkeypatches `aryx.cpq.engine._fill_signature` directly -- a
`from ... import` would freeze a reference at import time and silently
make that monkeypatch a no-op.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module
from aryx.cpq.constraint_rules.constraint_rules_apply import apply_rules
from aryx.cpq.constraint_rules.constraint_rules_fallback import resolve_empty_intersections
from aryx.cpq.constraint_rules.constraint_rules_narrowing import apply_narrowing_rec_rules
from aryx.cpq.engine import logger


def apply_constraint_rules(
    engine: Any,
    attrs: list[Any],
    rules: list[Any],
    filled: dict[str, str],
    bml_eval: Any | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    _dt_cache: dict[tuple[int, str], tuple] | None = None,
    _constraint_cache: dict[str, tuple] | None = None,
    _signature_exclude_vns: frozenset[str] | None = None,
    narrowing_rec_rules: list[Any] | None = None,
) -> dict[int, list[str]]:
    """Return {attr_entity_id: [allowed_item_values]} for attrs with
    active constraints. Multiple rules for the same target are
    intersected (AND semantics). Script-backed rules (rule.script set)
    derive their allowed list from the BML evaluator using the current
    filled variables; an unknown script outcome (None) applies no
    constraint rather than allowing everything.

    narrowing_rec_rules — optional (default None, no-op for every
    existing caller) — see constraint_rules_narrowing.py's docstring.

    filled_multi — see apply_hiding_rules; only consulted for
    declarative conditions on a select_type=="multi" attribute
    (operators "7"/"8").

    _constraint_cache — docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md
    (RC6, 2026-08-24): optional, mutated in place. When supplied, this
    method's real evaluation is skipped and the previous pass's result
    returned directly when nothing in `_fill_signature(filled,
    filled_multi, visible_ids)`'s broad snapshot has changed since it
    was last computed THIS TURN. `None` (the default) is a complete
    no-op, identical to every pre-existing call site. Owned by
    `evaluate_rules_loop`, which declares one fresh dict per turn, so
    pass 0 of every turn always computes fresh -- same lifecycle as
    `_default_fill_signatures`. Returned as a shallow copy since a
    caller (`_apply_series_mapping_exclusions`) reassigns individual
    keys of the dict it receives.

    _signature_exclude_vns — same RC5 mechanism `auto_fill` uses: vns
    already proven non-convergent churn this turn are excluded from the
    signature above, so a permanently flip-flopping attribute never
    defeats this cache. `None` (the default) includes everything.
    """
    if not rules and not narrowing_rec_rules:
        return {}
    _cur_sig = None
    if _constraint_cache is not None:
        # RC6, 2026-08-24: exclude vns already proven (this turn) to be
        # non-convergent churn (RC5's _oscillating_vns) from the
        # signature -- otherwise a permanently-flip-flopping attribute
        # (e.g. a resync_stale_recommendations disagreement) would
        # change this signature every single pass and defeat this cache
        # exactly the way it defeated auto_fill's before RC5.
        _sig_filled = (
            filled if not _signature_exclude_vns else
            {k: v for k, v in filled.items() if k not in _signature_exclude_vns}
        )
        _sig_filled_multi = (
            filled_multi or {} if not _signature_exclude_vns else
            {k: v for k, v in (filled_multi or {}).items() if k not in _signature_exclude_vns}
        )
        _cur_sig = _engine_module._fill_signature(
            _sig_filled, _sig_filled_multi, {a.entity_id for a in attrs},
        )
        if _constraint_cache.get("sig") == _cur_sig:
            return dict(_constraint_cache["result"])

    by_rule_id = engine._attr_index(attrs)
    filled_by_rule_id = engine._filled_by_rule_id(attrs, filled, filled_multi)
    constrained: dict[int, list[str]] = {}
    # target.entity_id -> [(condition_key, normalized_allowed_values, rule_name)]
    # for every rule that actually fired -- condition_key groups rules
    # sharing the same declarative condition attribute set; script-backed
    # rules get a per-rule-unique key so they're never grouped/dropped.
    contributions: dict[int, list[tuple[frozenset, list[str], str]]] = {}

    apply_rules(
        rules, by_rule_id, filled, filled_by_rule_id, bml_eval, workspace_id,
        catalog_prefix, _dt_cache, constrained, contributions,
    )
    resolve_empty_intersections(rules, by_rule_id, constrained, contributions)
    if narrowing_rec_rules:
        apply_narrowing_rec_rules(
            narrowing_rec_rules, by_rule_id, filled, bml_eval, workspace_id,
            catalog_prefix, _dt_cache, constrained, contributions,
        )

    if constrained:
        names = [by_rule_id[eid].variable_name for eid in constrained if eid in by_rule_id]
        logger.info("cpq: constraint rules active for %s", names)
    if _constraint_cache is not None:
        _constraint_cache["sig"] = _cur_sig
        _constraint_cache["result"] = constrained
    return constrained
