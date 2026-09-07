"""Per-row orchestrator for `_load_value_rules` (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md): processes one fetched value rule through
script-backed actions, condition-context resolution, validation-rule
extraction, declarative-action bucketing, and final rule construction.
Logic unchanged from the original inline per-row loop body.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.value_rules_bucket import bucket_declarative_actions
from aryx.cpq.value_rules_condition import SKIP_ROW, compute_condition_context
from aryx.cpq.value_rules_finalize import finalize_rule_actions
from aryx.cpq.value_rules_script_actions import process_script_backed_actions
from aryx.cpq.value_rules_state import RuleLoadState
from aryx.cpq.value_rules_validation import append_validation_rules


def process_value_rule_row(
    engine: Any, state: RuleLoadState, eid: int, rule_name: str, fn_id: int,
    inp_list: list[tuple] | None, acts: list[tuple], scripts: dict[int, str],
) -> None:
    process_script_backed_actions(engine, state, eid, rule_name, fn_id, inp_list, acts, scripts)

    _ctx = compute_condition_context(engine, state, rule_name, fn_id, inp_list, scripts)
    if _ctx is SKIP_ROW:
        return
    condition_script, cond_attr_id, cond_value, cond_operator, declarative_condition_collision = _ctx

    append_validation_rules(
        state, eid, rule_name, acts, condition_script, cond_attr_id, cond_value,
        cond_operator, inp_list, declarative_condition_collision,
    )

    restrict_by_target, recommend_by_target, hide_targets = bucket_declarative_actions(
        state, eid, rule_name, acts)

    finalize_rule_actions(
        state, eid, rule_name, fn_id, condition_script, cond_attr_id, cond_value,
        cond_operator, inp_list, restrict_by_target, recommend_by_target,
        hide_targets, declarative_condition_collision,
    )
