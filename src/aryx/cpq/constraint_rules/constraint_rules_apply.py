"""Main rule-application loop for ``apply_constraint_rules`` (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) -- script-backed,
condition_script-backed, and declarative ConstraintRule evaluation.
Logic unchanged from the original inline loop.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.rule_trace import rule_trace
from aryx.cpq.constraint_rules.constraint_rules_intersect import intersect
from aryx.cpq.engine import (
    _condition_value_matches,
    _substitute_util_get_constraint_vals,
)
from aryx.cpq.bml.bml import evaluate_declarative_conditions


def apply_rules(
    rules: list[Any],
    by_rule_id: dict[int, Any],
    filled: dict[str, str],
    filled_by_rule_id: dict[int, str],
    bml_eval: Any | None,
    workspace_id: int | None,
    catalog_prefix: str,
    dt_cache: dict[tuple[int, str], tuple] | None,
    constrained: dict[int, list[str]],
    contributions: dict[int, list[tuple[frozenset, list[str], str]]],
) -> None:
    """Evaluate every rule in `rules`, intersecting each firing rule's
    allowed values into `constrained`/`contributions` in place.
    """
    for rule in rules:
        target = by_rule_id.get(rule.target_attr_id)
        if target is None:
            continue
        if rule.script is not None:
            if bml_eval is None:
                continue
            # Raven review (PR #269) asked whether this script-backed
            # REAL ConstraintRule branch should skip already-filled
            # targets the same way narrowing_rec_rules' loop below
            # does. Deliberately does NOT: find_rule_inconsistencies
            # consumes this exact output to check an ALREADY-FILLED
            # value against its own constraint set (the proactive
            # stale-constraint-reask feature) -- skipping filled
            # targets here would silently disable that check for
            # every script-backed constraint rule. narrowing_rec_
            # rules' guard is safe only because that loop's sole
            # consumer is display-time option narrowing; nothing
            # reads it for stale-value validation. A real perf issue
            # here (many script-backed ConstraintRules on filled
            # targets) needs its own opt-in flag so validation
            # callers keep evaluating everything while display-only
            # callers can skip -- not a copy of this guard.
            _script = _substitute_util_get_constraint_vals(
                rule.script, filled, workspace_id, catalog_prefix, dt_cache,
            )
            allowed = bml_eval.allowed_values_for_script(_script, filled)
            if allowed:
                intersect(
                    constrained, contributions, target, allowed,
                    frozenset({f"script:{rule.rule_name}"}), rule.rule_name,
                )
                rule_trace.record_fire(
                    rule_type="constraint", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome=f"allowed={allowed}",
                    bml_tier="script",
                )
            continue
        if rule.condition_script is not None:
            if bml_eval is None:
                continue
            fires = bml_eval.condition_holds(rule.condition_script, filled)
            if fires is True:
                intersect(
                    constrained, contributions, target, rule.allowed_values,
                    frozenset({f"condition_script:{rule.rule_name}"}), rule.rule_name,
                )
                rule_trace.record_fire(
                    rule_type="constraint", rule_id=rule.rule_name,
                    attr=target.variable_name,
                    outcome=f"allowed={rule.allowed_values}", bml_tier="condition_script",
                )
            continue  # False or unknown — never guess, no constraint applied
        if rule.conditions:
            matched, _blocked = evaluate_declarative_conditions(
                rule.conditions, filled_by_rule_id)
            if matched is not True:
                continue
            condition_key = frozenset(attr_id for attr_id, _value, _op in rule.conditions)
        else:
            if rule.condition_attr_id not in filled_by_rule_id:
                continue
            if not _condition_value_matches(
                filled_by_rule_id[rule.condition_attr_id], rule.condition_value,
                rule.condition_operator,
            ):
                continue
            condition_key = frozenset({rule.condition_attr_id})
        intersect(
            constrained, contributions, target, rule.allowed_values,
            condition_key, rule.rule_name,
        )
        rule_trace.record_fire(
            rule_type="constraint", rule_id=rule.rule_name,
            attr=target.variable_name, outcome=f"allowed={rule.allowed_values}",
        )
