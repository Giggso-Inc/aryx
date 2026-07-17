"""Value objects shared by deterministic CPQ validation layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, order=True)
class ValidationIssue:
    """One deterministic validation failure or coverage gap."""

    code: str
    message: str
    attribute: str = ""
    rule: str = ""
    expected: str = ""
    actual: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-ready issue representation."""
        return asdict(self)


@dataclass(frozen=True)
class Scenario:
    """One reproducible seed state for a rule-loop evaluation."""

    scenario_id: str
    filled: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    filled_multi: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleEvaluation:
    """Independent outcome of hide, recommend, and constraint rules."""

    hidden: frozenset[str]
    recommendations: dict[str, str]
    constraints: dict[str, tuple[str, ...]]
    unknown_rules: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class EvaluationResult:
    """Stable or failed fixed-point result for one scenario."""

    scenario_id: str
    filled: dict[str, str]
    sources: dict[str, str]
    hidden: frozenset[str]
    constraints: dict[str, tuple[str, ...]]
    pending: tuple[str, ...]
    unknown_rules: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]
    iterations: int
    converged: bool
    cycle_detected: bool
    seed: dict[str, str] = field(default_factory=dict)
    trace: tuple[dict[str, Any], ...] = ()
    filled_multi: dict[str, tuple[str, ...]] = field(default_factory=dict)
    seed_multi: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True only for a converged scenario with no reported issues."""
        return self.converged and not self.issues and not self.cycle_detected

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministically ordered JSON-ready result."""
        return {
            "scenario_id": self.scenario_id,
            "filled": dict(sorted(self.filled.items())),
            "filled_multi": {
                key: list(self.filled_multi[key]) for key in sorted(self.filled_multi)
            },
            "sources": dict(sorted(self.sources.items())),
            "hidden": sorted(self.hidden),
            "constraints": {key: list(self.constraints[key]) for key in sorted(self.constraints)},
            "pending": list(self.pending),
            "unknown_rules": list(self.unknown_rules),
            "issues": [issue.to_dict() for issue in sorted(self.issues)],
            "iterations": self.iterations,
            "converged": self.converged,
            "cycle_detected": self.cycle_detected,
            "seed": dict(sorted(self.seed.items())),
            "seed_multi": {
                key: list(self.seed_multi[key]) for key in sorted(self.seed_multi)
            },
            "trace": list(self.trace),
            "passed": self.passed,
        }
