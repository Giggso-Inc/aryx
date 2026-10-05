"""Final per-row rule construction from the bucketed restrict/recommend/
hide targets, split out of `_load_value_rules`'s per-row loop body (Phase
4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from
the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.bml.bml_condition_expression import copy_conditions
from aryx.cpq.engine import ConstraintRule, HidingRule, RecommendationRule, logger
from aryx.cpq.value_rules.value_rules_state import RuleLoadState


def finalize_rule_actions(
    state: RuleLoadState, eid: int, rule_name: str, fn_id: int,
    condition_script: str | None, cond_attr_id: int, cond_value: str,
    cond_operator: str, inp_list: list[tuple] | None,
    restrict_by_target: dict[int, list[str]],
    recommend_by_target: dict[int, str], hide_targets: set[int],
    declarative_condition_collision: bool,
) -> None:
    if condition_script:
        if restrict_by_target or recommend_by_target:
            state.script_condition_gated += 1
            logger.info(
                "cpq: rule %r has a script condition "
                "(condition_function_id=%d) gating a declarative "
                "action — evaluated via BmlEvaluator at apply time",
                rule_name, fn_id)
        else:
            # Script condition but no declarative action to gate
            # (e.g. the action was itself script-backed and
            # already wired above, or genuinely has no action) —
            # nothing left for condition_script to attach to.
            state.cond_script_skipped += 1
            logger.info(
                "cpq: rule %r has a script condition "
                "(condition_function_id=%d) but no declarative "
                "action — nothing to gate", rule_name, fn_id)
    for target_attr_id, allowed in restrict_by_target.items():
        if declarative_condition_collision:
            state.constraint_collisions_skipped += 1
            continue
        state.con_rules.append(ConstraintRule(
            rule_name=rule_name or str(eid),
            condition_attr_id=cond_attr_id,
            condition_value=cond_value,
            condition_operator=cond_operator,
            target_attr_id=target_attr_id,
            allowed_values=allowed,
            conditions=copy_conditions(inp_list) if condition_script is None else None,
            condition_script=condition_script,
        ))
    for target_attr_id, rec_val in recommend_by_target.items():
        if declarative_condition_collision:
            state.recommendation_collisions_skipped += 1
            continue
        state.rec_rules.append(RecommendationRule(
            rule_name=rule_name or str(eid),
            condition_attr_id=cond_attr_id,
            condition_value=cond_value,
            condition_operator=cond_operator,
            target_attr_id=target_attr_id,
            recommended_value=rec_val,
            conditions=copy_conditions(inp_list) if condition_script is None else None,
            condition_script=condition_script,
        ))
    for target_attr_id in hide_targets:
        if declarative_condition_collision:
            state.hiding_collisions_skipped += 1
            continue
        state.hiding_rules.append(HidingRule(
            rule_name=rule_name or str(eid),
            condition_attr_id=cond_attr_id,
            condition_value=cond_value,
            condition_operator=cond_operator,
            target_attr_id=target_attr_id,
            hide=True,
            script=condition_script,
            conditions=copy_conditions(inp_list) if condition_script is None else None,
        ))
