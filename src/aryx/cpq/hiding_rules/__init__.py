"""Hiding-rule load/apply cluster plus the rule-id indexing and
active-source-widening helpers that share its rule-id conventions
(Phase 4 step 4 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Re-exports every function so ``from aryx.cpq.hiding_rules import <name>``
works regardless of which submodule actually defines it.
"""

from __future__ import annotations

from aryx.cpq.hiding_rules.apply import apply_hiding_rules
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.hiding_rules.data_table_forced import _data_table_forced_vns
from aryx.cpq.hiding_rules.loader import load_hiding_rules
from aryx.cpq.hiding_rules.rule_forced import (
    _rule_forced_from_active_decision_vns,
)

__all__ = [
    "_attr_index",
    "_data_table_forced_vns",
    "_filled_by_rule_id",
    "_rule_forced_from_active_decision_vns",
    "apply_hiding_rules",
    "load_hiding_rules",
]
