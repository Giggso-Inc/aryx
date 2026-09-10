"""Result dataclasses for the BOM gate.

Split out of `cpq/bom_gate.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aryx.cpq.state import ConfigAttr


@dataclass
class StaleConstraintViolation:
    """A filled attr whose value no longer satisfies the freshly recomputed
    constraint. Auto-clearable — unlike a provenance failure, the engine
    knows exactly what's wrong (this value isn't in `allowed` anymore) but
    can't guess the right replacement, so the caller re-asks rather than
    silently picking one or hard-blocking (docs/
    CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1 — same "never guess"
    reasoning already established for this class of issue elsewhere)."""

    attr: ConfigAttr
    current_value: str
    allowed: list[str]


@dataclass
class BomGateResult:
    ok: bool
    errors: list[str]
    stale_violations: list[StaleConstraintViolation] = field(default_factory=list)
    catch_message: str = ""
