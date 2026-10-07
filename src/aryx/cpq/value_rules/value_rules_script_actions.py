"""Script-backed value-rule actions (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md), split out of `_load_value_rules`'s per-row loop body.
Logic unchanged from the original inline block.
"""

from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq.bml.bml_condition_expression import copy_conditions
from aryx.cpq.engine import ConstraintRule, RecommendationRule, logger
from aryx.cpq.value_rules.value_rules_constraint_mode import parse_constraint_mode
from aryx.cpq.value_rules.value_rules_state import RuleLoadState


def _mode_rule(
    state: RuleLoadState, eid: int, rule_name: str, aid: int,
    inp_list: list[tuple] | None, script: str,
) -> bool:
    """Plan F2 (flag `cpq_constraint_mode_enabled`): a script that sets an
    ALLOW/DISALLOW list through `setConstraintValuesInSession` becomes a
    declarative, mode-carrying ConstraintRule gated by the rule's own inputs.
    False (nothing appended) when the flag is off or the script is not that shape."""
    if not get_settings().cpq_constraint_mode_enabled:
        return False
    parsed = parse_constraint_mode(script)
    if parsed is None:
        return False
    state.con_rules.append(ConstraintRule(
        rule_name=rule_name or str(eid),
        condition_attr_id=(inp_list[-1][0] if inp_list else 0),
        condition_value="",
        target_attr_id=aid,
        allowed_values=parsed.values,
        conditions=copy_conditions(inp_list) if inp_list else None,
        mode=parsed.mode,
        guard_attr=parsed.guard_var,
        blank=parsed.blank,
    ))
    state.script_constraints += 1
    return True


def process_script_backed_actions(
    engine: Any, state: RuleLoadState, eid: int, rule_name: str, fn_id: int,
    inp_list: list[tuple] | None, acts: list[tuple], scripts: dict[int, str],
) -> None:
    """Script-backed actions: gated by set_type same as declarative
    ones. set_type == -1 -> the BML function returns the allowed
    list at apply time (constraint semantics, handled by the
    existing BML evaluator path). Any other set_type is a
    script-backed RECOMMENDATION/default -- now wired to
    RecommendationRule.script + apply_recommendation_rules'
    BmlEvaluator hookup (previously extracted but never
    evaluated at all -- see docs/CPQ_RULE_TOOL_FLOW_PLAN.md
    item 2/§7-8's confirmed "APX NEXT ENHANCED product +
    non-Enhanced hardware" inconsistency this closes).
    """
    for aid, _at, _val, act_fn, act_set_type, _comments in acts:
        if act_fn == -1:
            continue
        script = scripts.get(act_fn)
        if not script:
            logger.warning(
                "cpq: rule %r references function_id=%d but no "
                "BmFunction script was found", rule_name, act_fn)
        elif act_set_type == -1 and _mode_rule(state, eid, rule_name, aid, inp_list, script):
            continue
        elif act_set_type == -1:
            state.con_rules.append(ConstraintRule(
                rule_name=rule_name or str(eid),
                condition_attr_id=(inp_list[-1][0] if inp_list else 0),
                condition_value="",
                target_attr_id=aid,
                allowed_values=[],
                script=script,
            ))
            state.script_constraints += 1
        else:
            # Live-confirmed gap (2026-08-25, SVX "Force Set
            # Quantity of Body Worn Cameras with sum of
            # Mounting"): this rule's own gating condition
            # (fn_id) can ALSO be script-backed independently
            # of its script-backed action -- previously
            # dropped entirely (condition_attr_id hardcoded
            # to 0, no condition_script), so the rule had no
            # way to know when to fire and never applied.
            # Attach it here too, generic to any rule with
            # this same dual-script shape. D2 "never guess"
            # still holds via apply_recommendation_rules'
            # own condition_holds check.
            _rec_condition_script = (
                scripts.get(fn_id) if fn_id != -1 else None
            )
            state.rec_rules.append(RecommendationRule(
                rule_name=rule_name or str(eid),
                condition_attr_id=0,
                condition_value="",
                target_attr_id=aid,
                script=script,
                condition_script=_rec_condition_script,
                conditions=(copy_conditions(inp_list)
                            if inp_list and get_settings().cpq_script_rec_rule_conditions_enabled else None),
            ))
            state.script_recommendations_wired += 1
            logger.info(
                "cpq: rule %r is a script-backed recommendation "
                "(function_id=%d, target=%d) — evaluated via "
                "BmlEvaluator at apply time",
                rule_name, act_fn, aid)
