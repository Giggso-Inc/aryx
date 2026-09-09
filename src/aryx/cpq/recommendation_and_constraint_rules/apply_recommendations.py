"""``apply_recommendation_rules`` -- fire recommendation rules against the
current filled state (Phase 4 step 6 extraction from ``cpq/engine.py``,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Stateless and purely functional -- no ``CpqEngine`` instance needed; its
two former ``self.`` helpers are the plain functions in
``aryx.cpq.hiding_rules.attr_index`` that ``CpqEngine._attr_index``/
``_filled_by_rule_id`` themselves now delegate to.
"""

from __future__ import annotations

from aryx.cpq import rule_trace
from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.engine import _valid, logger
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.recommendation_and_constraint_rules.rule_condition import (
    resolve_recommended_value,
)
from aryx.cpq.state import ConfigAttr, RecommendationRule


def apply_recommendation_rules(
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    rules: list[RecommendationRule],
    bml_eval: BmlEvaluator | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    constrained_opts: dict[int, list[str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """Apply recommendation rules. Returns {variable_name: (item_value, display)}.

    Only fills attrs that are not already filled. Does not override prior
    user selections or auto-fills from earlier loop iterations.

    Script-backed rules (rule.script set) derive their recommended value
    from the BML evaluator using the current filled variables — same
    Tier-1/Tier-2 machinery apply_constraint_rules already uses via
    BmlEvaluator.allowed_values_for_script. Closes the gap where
    script-backed recommendations were extracted but never evaluated
    (RecommendationRule previously had no script field/hookup at all —
    see docs/CPQ_RULE_TOOL_FLOW_PLAN.md item 2/§7-8's confirmed
    "APX NEXT ENHANCED product + non-Enhanced hardware" inconsistency).
    A script resolving to anything other than EXACTLY one value (None,
    or 2+ candidates) is treated as "not yet determined" and skipped —
    same D2 "never guess" principle as the existing tilde-delimited
    ambiguous-recommendation skip below. bml_eval=None (caller opted
    out) silently skips script-backed rules, same as apply_constraint_rules.

    filled_multi — see apply_hiding_rules; only consulted for
    declarative conditions on a select_type=="multi" attribute
    (operators "7"/"8").

    constrained_opts — this function runs BEFORE apply_constraint_rules
    recomputes it for the CURRENT pass (evaluate_rules_loop's own
    "hide -> auto_fill -> recommend -> constrain" order), so what's
    passed in here is necessarily the PREVIOUS pass's result — still
    the best available signal, and correct at the fixed point once the
    loop converges. Live regression: without this, a recommendation
    whose OWN condition never depends on the attribute a DIFFERENT,
    active constraint just narrowed (e.g. "Default Service Type based
    on Solution Type selected" vs. a Hardware-Version-keyed constraint
    on the same target) kept unconditionally re-asserting its value
    the instant auto_fill's own re-validation correctly dropped it —
    every pass, forever, since this function only checks "is the
    target currently filled at all", never "is this specific value
    still valid". evaluate_rules_loop's fixed-point check compares KEY
    sets, not values, so a target that's drop-then-immediately-refilled
    to the SAME stale value every pass looked stable and converged
    with the wrong answer, silently reporting a complete configuration
    that a separate BOM-gate consistency check only caught one turn
    later. None (caller opted out, e.g. the constraint pass hasn't run
    even once yet) applies no filter, same "unknown -> don't guess a
    restriction that isn't provably there" convention used everywhere
    else a constraint is optional in this module.
    """
    if not rules:
        return {}
    by_rule_id = _attr_index(attrs)
    filled_by_rule_id = _filled_by_rule_id(attrs, filled, filled_multi)
    new_fills: dict[str, tuple[str, str]] = {}
    for rule in rules:
        target = by_rule_id.get(rule.target_attr_id)
        # A truthy check, not `in filled` — an empty string is D4's
        # deliberate "user cleared this" marker
        # (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md), the single-select
        # counterpart of filled_multi's existing "(none)" convention.
        # A genuine rule re-assertion must still override it (same as
        # it would override any other stale value) — only a REAL
        # value already present blocks this rule from firing.
        if not target or filled.get(target.variable_name):
            continue
        recommended_value = resolve_recommended_value(
            rule, filled, filled_by_rule_id, bml_eval)
        if recommended_value is None:
            continue
        matched_display = next(
            (o.display_name for o in target.options
             if o.item_value.lower() == recommended_value.lower()),
            recommended_value,
        )
        if not _valid(recommended_value):
            continue
        allowed_for_target = (
            constrained_opts.get(target.entity_id) if constrained_opts else None
        )
        if allowed_for_target is not None and not any(
            recommended_value.lower() == v.lower() for v in allowed_for_target
        ):
            # A DIFFERENT, already-active constraint has ruled this
            # value out — never re-assert it just because this rule's
            # own condition doesn't happen to mention that constraint.
            continue
        new_fills[target.variable_name] = (recommended_value, matched_display)
        rule_trace.record_fire(
            rule_type="recommendation", rule_id=rule.rule_name,
            attr=target.variable_name, outcome=f"set={recommended_value}",
            bml_tier="script" if rule.script is not None else None,
        )
    if new_fills:
        logger.info("cpq: recommendation rules auto-filled %s", list(new_fills.keys()))
    return new_fills
