"""Stable report aggregation for the CPQ validation CLI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aryx.cpq.validation.models import EvaluationResult, ValidationIssue


@dataclass(frozen=True)
class ScenarioValidation:
    """One oracle result plus production comparison findings."""

    result: EvaluationResult
    comparison_issues: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready scenario record."""
        data = self.result.to_dict()
        data["comparison_issues"] = [issue.to_dict() for issue in self.comparison_issues]
        return data


@dataclass(frozen=True)
class ValidationReport:
    """Catalog-level deterministic validation report."""

    product: str
    workspace_id: int
    validations: tuple[ScenarioValidation, ...]

    @property
    def failed(self) -> int:
        """Count scenarios with oracle or comparison failures."""
        return sum(
            not validation.result.passed or bool(validation.comparison_issues)
            for validation in self.validations
        )

    @property
    def unknown(self) -> int:
        """Count unique scenarios containing unresolved deterministic BML."""
        return sum(bool(validation.result.unknown_rules) for validation in self.validations)

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready catalog report."""
        return {
            "product": self.product,
            "workspace_id": self.workspace_id,
            "summary": {
                "scenarios": len(self.validations),
                "failed": self.failed,
                "unknown": self.unknown,
                "passed": len(self.validations) - self.failed,
            },
            "scenarios": [validation.to_dict() for validation in self.validations],
        }
