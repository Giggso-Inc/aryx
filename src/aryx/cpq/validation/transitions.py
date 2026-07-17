"""Deterministic state transitions used by the fixed-point runner."""
from __future__ import annotations

from aryx.cpq.validation.models import ValidationIssue
from aryx.cpq.validation.oracle import DeterministicRuleOracle


def apply_recommendations(
    oracle: DeterministicRuleOracle,
    recommendations: dict[str, str],
    hidden: frozenset[str],
    filled: dict[str, str],
    filled_multi: dict[str, tuple[str, ...]],
    sources: dict[str, str],
) -> None:
    """Apply recommendations without overwriting explicit user choices."""
    for variable, source in tuple(sources.items()):
        if source != "rule" or variable in recommendations:
            continue
        filled.pop(variable, None)
        filled_multi.pop(variable, None)
        sources.pop(variable, None)
    for variable, value in sorted(recommendations.items()):
        if variable in hidden or sources.get(variable) == "user":
            continue
        attr = next((item for item in oracle.attrs if item.variable_name == variable), None)
        if attr is not None and attr.select_type == "multi":
            filled_multi[variable] = (value,)
            filled.pop(variable, None)
        else:
            filled[variable] = value
            filled_multi.pop(variable, None)
        sources[variable] = "rule"


def apply_constraints(
    constraints: dict[str, tuple[str, ...]],
    filled: dict[str, str],
    filled_multi: dict[str, tuple[str, ...]],
    sources: dict[str, str],
    issues: set[ValidationIssue],
) -> set[str]:
    """Invalidate non-user values and flag explicit invalid user choices."""
    invalid_user: set[str] = set()
    for variable, allowed in sorted(constraints.items()):
        if variable in filled_multi:
            _constrain_multi(
                variable, allowed, filled_multi, sources, invalid_user, issues,
            )
            continue
        value = filled.get(variable)
        if value is None or value in allowed:
            continue
        if sources.get(variable) == "user":
            invalid_user.add(variable)
            issues.add(ValidationIssue(
                "constraint_user_value", "user value is outside the active allowed set",
                variable, expected=repr(allowed), actual=value,
            ))
            continue
        if sources.get(variable) == "rule":
            issues.add(ValidationIssue(
                "recommendation_outside_constraint",
                "recommended value is outside the active allowed set",
                variable, expected=repr(allowed), actual=value,
            ))
        filled.pop(variable, None)
        sources.pop(variable, None)
    return invalid_user


def _constrain_multi(
    variable: str, allowed: tuple[str, ...],
    filled_multi: dict[str, tuple[str, ...]], sources: dict[str, str],
    invalid_user: set[str], issues: set[ValidationIssue],
) -> None:
    """Constrain one multi-select while preserving explicit user choices."""
    selected = filled_multi[variable]
    invalid = tuple(value for value in selected if value not in allowed)
    if not invalid:
        return
    if sources.get(variable) == "user":
        invalid_user.add(variable)
        issues.add(ValidationIssue(
            "constraint_user_value", "user selections are outside the active allowed set",
            variable, expected=repr(allowed), actual=repr(invalid),
        ))
        return
    kept = tuple(value for value in selected if value in allowed)
    if kept:
        filled_multi[variable] = kept
    else:
        filled_multi.pop(variable, None)
        sources.pop(variable, None)


def auto_fill(
    oracle: DeterministicRuleOracle,
    hidden: frozenset[str],
    constraints: dict[str, tuple[str, ...]],
    filled: dict[str, str],
    filled_multi: dict[str, tuple[str, ...]],
    sources: dict[str, str],
) -> None:
    """Apply defaults or a sole allowed option only after all rule phases."""
    for attr in oracle.attrs:
        variable = attr.variable_name
        if variable in hidden or variable in filled or variable in filled_multi:
            continue
        options = tuple(option.item_value for option in sorted(
            attr.options, key=lambda option: (option.order, option.item_value),
        ))
        allowed = constraints.get(variable, options)
        default_allowed = variable not in constraints or attr.default_value in allowed
        if attr.select_type == "multi":
            if attr.default_value and default_allowed:
                filled_multi[variable], sources[variable] = (attr.default_value,), "default"
            elif variable in constraints and allowed:
                filled_multi[variable], sources[variable] = tuple(allowed), "constraint"
            continue
        if attr.default_value and default_allowed:
            filled[variable], sources[variable] = attr.default_value, "default"
        elif not attr.hidden and len(allowed) == 1:
            filled[variable], sources[variable] = allowed[0], "constraint"
