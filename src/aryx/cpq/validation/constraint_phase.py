"""Independent constraint-rule phase for the CPQ reference oracle."""
from __future__ import annotations

from aryx.cpq.state import ConstraintRule
from aryx.cpq.validation.conditions import ConditionEvaluator
from aryx.cpq.validation.models import ValidationIssue
from aryx.cpq.validation.script_oracle import DeterministicBmlOracle


def evaluate_constraints(
    rules: tuple[ConstraintRule, ...],
    conditions: ConditionEvaluator,
    scripts: DeterministicBmlOracle,
    filled: dict[str, str],
    filled_multi: dict[str, tuple[str, ...]],
    variables: dict[str, str],
) -> tuple[dict[str, tuple[str, ...]], set[str], list[ValidationIssue]]:
    """Evaluate and intersect every active constraint in stable order."""
    constraints: dict[str, tuple[str, ...]] = {}
    unknown: set[str] = set()
    issues: list[ValidationIssue] = []
    for rule in rules:
        target = conditions.target(rule, issues)
        if target is None:
            continue
        allowed = scripts.values(rule.script, variables) if rule.script else None
        active = (
            True if rule.script and allowed is not None
            else conditions.status(rule, filled, filled_multi)
        )
        if rule.script and allowed is None:
            if not scripts.supports_values(rule.script):
                unknown.add(rule.rule_name)
            continue
        if active is None:
            if rule.condition_script and not scripts.supports_condition(rule.condition_script):
                unknown.add(rule.rule_name)
            continue
        if not active:
            continue
        values = tuple(allowed if rule.script else rule.allowed_values)
        current = constraints.get(target.variable_name)
        constraints[target.variable_name] = values if current is None else tuple(
            value for value in current if value in set(values)
        )
    for variable, allowed_values in sorted(constraints.items()):
        if not allowed_values:
            issues.append(ValidationIssue(
                "empty_constraint", "active constraints have an empty intersection", variable,
            ))
    return constraints, unknown, issues
