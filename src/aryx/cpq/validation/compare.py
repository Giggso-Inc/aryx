"""Compare independent oracle results with production rule-loop state."""
from __future__ import annotations

from dataclasses import dataclass, field

from aryx.cpq.validation.models import EvaluationResult, ValidationIssue


@dataclass(frozen=True)
class ProductionState:
    """Production dimensions relevant to deterministic comparison."""

    filled: dict[str, str]
    visible: frozenset[str]
    constraints: dict[str, tuple[str, ...]]
    pending: tuple[str, ...]
    filled_multi: dict[str, tuple[str, ...]] = field(default_factory=dict)


def compare_states(
    expected: EvaluationResult,
    actual: ProductionState,
    *,
    all_attributes: set[str],
) -> tuple[ValidationIssue, ...]:
    """Return one classified issue for each mismatching state dimension."""
    issues: list[ValidationIssue] = []
    expected_visible = frozenset(all_attributes - set(expected.hidden))
    _compare(issues, "filled_mismatch", expected.filled, actual.filled)
    _compare(issues, "multi_mismatch", expected.filled_multi, actual.filled_multi)
    _compare(issues, "visibility_mismatch", expected_visible, actual.visible)
    _compare(issues, "constraint_mismatch", expected.constraints, actual.constraints)
    _compare(issues, "pending_mismatch", expected.pending, actual.pending)
    return tuple(sorted(issues))


def compare_rule_order(
    original: ProductionState, reordered: ProductionState,
) -> tuple[ValidationIssue, ...]:
    """Report production behavior that depends on input rule-list order."""
    if original == reordered:
        return ()
    return (ValidationIssue(
        "rule_order_dependence",
        "production result changed when every rule list was reversed",
        expected=repr(original), actual=repr(reordered),
    ),)


def _compare(
    issues: list[ValidationIssue], code: str, expected: object, actual: object,
) -> None:
    """Append a stable mismatch issue when two dimensions differ."""
    if expected == actual:
        return
    issues.append(ValidationIssue(
        code, code.replace("_", " "), expected=repr(expected), actual=repr(actual),
    ))
