"""Shared mutable state for `_load_value_rules`'s per-rule classification
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). One
`RuleLoadState` is built once per `_load_value_rules` call and threaded
through every row-processing helper in `value_rules_row.py` and its
sub-helpers; the accumulated rule lists and counters are read back by
`value_rules_load.py` for the final summary log lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleLoadState:
    ingest_store: Any = None
    existing_questions: dict[str, Any] = field(default_factory=dict)
    workspace_id: int = 0
    rec_rules: list[Any] = field(default_factory=list)
    con_rules: list[Any] = field(default_factory=list)
    validation_rules: list[Any] = field(default_factory=list)
    hiding_rules: list[Any] = field(default_factory=list)
    script_constraints: int = 0
    script_recommendations_wired: int = 0
    cond_script_skipped: int = 0
    script_condition_gated: int = 0
    ambiguous_recommendations_skipped: int = 0
    assign_all_answers_blocked: int = 0
    unrecognized_answers_requeued: int = 0
    validation_collisions_skipped: int = 0
    constraint_collisions_skipped: int = 0
    recommendation_collisions_skipped: int = 0
    hiding_collisions_skipped: int = 0
