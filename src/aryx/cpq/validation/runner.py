"""Fixed-point runner for hide → recommend → constrain → final auto-fill."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aryx.cpq.validation.models import EvaluationResult, Scenario, ValidationIssue
from aryx.cpq.validation.oracle import DeterministicRuleOracle
from aryx.cpq.validation.trace import state_fingerprint, trace_entry
from aryx.cpq.validation.transitions import apply_constraints, apply_recommendations, auto_fill


@dataclass
class _Iteration:
    """Mutable state produced by one deterministic pass."""

    filled: dict[str, str]
    filled_multi: dict[str, tuple[str, ...]]
    sources: dict[str, str]
    hidden: frozenset[str]
    constraints: dict[str, tuple[str, ...]]
    pending: tuple[str, ...]
    unknown: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]


def evaluate_to_fixed_point(
    oracle: DeterministicRuleOracle,
    scenario: Scenario,
    *,
    strict_unknown: bool = False,
    max_iterations: int | None = None,
) -> EvaluationResult:
    """Evaluate one seed until the complete state stabilizes or cycles."""
    limit = max_iterations or max(16, len(oracle.attrs) * 4)
    filled = dict(scenario.filled)
    filled_multi = dict(scenario.filled_multi)
    sources = dict(scenario.sources)
    seen: dict[tuple[Any, ...], int] = {}
    all_issues: set[ValidationIssue] = set()
    trace: list[dict[str, Any]] = []
    previous: tuple[Any, ...] | None = None
    current: _Iteration | None = None
    for iteration in range(1, limit + 1):
        current = _run_iteration(oracle, filled, filled_multi, sources, strict_unknown)
        trace.append(trace_entry(
            iteration, current.filled, current.filled_multi, current.hidden,
            current.constraints, current.pending, current.unknown,
        ))
        all_issues.update(current.issues)
        fingerprint = state_fingerprint(
            current.filled, current.filled_multi, current.sources, current.hidden,
            current.constraints, current.pending, current.unknown,
        )
        if fingerprint == previous:
            return _result(scenario, current, all_issues, trace, iteration, True, False)
        if fingerprint in seen:
            all_issues.add(ValidationIssue(
                "evaluation_cycle",
                f"state repeated from iteration {seen[fingerprint]}",
            ))
            return _result(scenario, current, all_issues, trace, iteration, False, True)
        seen[fingerprint] = iteration
        previous = fingerprint
        filled, filled_multi, sources = current.filled, current.filled_multi, current.sources
    assert current is not None
    all_issues.add(ValidationIssue("iteration_limit", f"did not converge in {limit} passes"))
    return _result(scenario, current, all_issues, trace, limit, False, False)


def _run_iteration(
    oracle: DeterministicRuleOracle,
    prior_filled: dict[str, str],
    prior_multi: dict[str, tuple[str, ...]],
    prior_sources: dict[str, str],
    strict_unknown: bool,
) -> _Iteration:
    """Run one ordered hide, recommend, constraint, and auto-fill pass."""
    filled, sources = dict(prior_filled), dict(prior_sources)
    filled_multi = dict(prior_multi)
    first = oracle.evaluate_rules(filled, filled_multi)
    static_hidden = {attr.variable_name for attr in oracle.attrs if attr.hidden}
    rule_hidden = first.hidden
    hidden = frozenset(set(rule_hidden) | static_hidden)
    for variable in rule_hidden:
        filled.pop(variable, None)
        filled_multi.pop(variable, None)
        sources.pop(variable, None)
    apply_recommendations(
        oracle, first.recommendations, rule_hidden, filled, filled_multi, sources,
    )
    second = oracle.evaluate_rules(filled, filled_multi)
    issues = set(first.issues) | set(second.issues)
    invalid_user = apply_constraints(
        second.constraints, filled, filled_multi, sources, issues,
    )
    auto_fill(oracle, rule_hidden, second.constraints, filled, filled_multi, sources)
    visible = [attr for attr in oracle.attrs if attr.variable_name not in hidden]
    pending = tuple(sorted(
        {attr.variable_name for attr in visible
         if attr.variable_name not in filled and attr.variable_name not in filled_multi}
        | invalid_user,
    ))
    unknown = tuple(sorted(set(first.unknown_rules) | set(second.unknown_rules)))
    if strict_unknown:
        issues.update(ValidationIssue(
            "unknown_script", "deterministic BML oracle could not resolve the rule", rule=name,
        ) for name in unknown)
    return _Iteration(filled, filled_multi, sources, hidden, second.constraints, pending, unknown,
                      tuple(sorted(issues)))


def _result(
    scenario: Scenario, state: _Iteration, issues: set[ValidationIssue],
    trace: list[dict[str, Any]], iterations: int, converged: bool, cycle: bool,
) -> EvaluationResult:
    """Build an immutable public result."""
    return EvaluationResult(
        scenario_id=scenario.scenario_id,
        filled=state.filled,
        sources=state.sources,
        hidden=state.hidden,
        constraints=state.constraints,
        pending=state.pending,
        unknown_rules=state.unknown,
        issues=tuple(sorted(issues)),
        iterations=iterations,
        converged=converged,
        cycle_detected=cycle,
        seed=dict(scenario.filled),
        trace=tuple(trace),
        filled_multi=state.filled_multi,
        seed_multi=dict(scenario.filled_multi),
    )
