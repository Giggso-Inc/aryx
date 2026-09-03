"""Dataclasses for the post-ingest zero-loss validation layer: ground-truth
shapes derived from source data, and the check-result/report shapes the
validator produces.

Split out of `pipeline/ingest_validation.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FkTruth:
    """One deterministic FK reference set between two datasets."""

    child_dataset: str
    fk_column: str
    parent_dataset: str
    resolvable_child_ids: set[str] = field(default_factory=set)
    dangling_values: set[str] = field(default_factory=set)


@dataclass
class DatasetTruth:
    """Expected content for one ingested dataset (CSV stem)."""

    rows: int
    id_column: str | None
    id_values: set[str] = field(default_factory=set)
    element_tag: str | None = None
    headers: list[str] = field(default_factory=list)


@dataclass
class GroundTruth:
    """Everything the source says must exist after ingestion."""

    datasets: dict[str, DatasetTruth] = field(default_factory=dict)
    fk_refs: list[FkTruth] = field(default_factory=list)
    raw_xml_counts: dict[str, int] | None = None  # tier 2 only: element tag -> count


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARN | SKIP
    expected: Any
    actual: Any
    detail: str = ""


@dataclass
class ValidationReport:
    workspace_id: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "FAIL" for c in self.checks)

    def summary_line(self) -> str:
        by = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
        for c in self.checks:
            by[c.status] = by.get(c.status, 0) + 1
        return (f"checks={len(self.checks)} pass={by['PASS']} fail={by['FAIL']} "
                f"warn={by['WARN']} skip={by['SKIP']}")

    def failures(self) -> list[str]:
        return [f"{c.name}: expected={c.expected} actual={c.actual} {c.detail}".strip()
                for c in self.checks if c.status == "FAIL"]

    def render(self) -> str:
        lines = [f"=== Ingest validation — workspace {self.workspace_id} ===",
                 self.summary_line(), ""]
        for c in self.checks:
            lines.append(f"[{c.status}] {c.name}")
            lines.append(f"    expected: {c.expected}")
            lines.append(f"    actual:   {c.actual}")
            if c.detail:
                lines.append(f"    detail:   {c.detail}")
        lines.append("")
        lines.append(f"RESULT: {'PASSED' if self.passed else 'FAILED'}")
        return "\n".join(lines)
