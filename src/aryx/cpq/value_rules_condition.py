"""Per-rule condition context (condition_script/cond_attr_id/cond_value/
cond_operator, plus the same-attribute operator-collision guard) split
out of `_load_value_rules`'s per-row loop body (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
block.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import logger
from aryx.cpq.value_rules_state import RuleLoadState

# Sentinel returned when the rule has no usable condition and the caller
# must `continue` to the next fetched row, exactly as the original inline
# `continue` did.
SKIP_ROW = object()


def compute_condition_context(
    engine: Any, state: RuleLoadState, rule_name: str, fn_id: int,
    inp_list: list[tuple] | None, scripts: dict[int, str],
) -> tuple[str | None, int, str, str, bool] | object:
    """Returns (condition_script, cond_attr_id, cond_value, cond_operator,
    declarative_condition_collision), or the `SKIP_ROW` sentinel when this
    row has no usable condition at all.
    """
    condition_script: str | None = None
    if fn_id != -1:
        # Condition itself is a script (boolean BML), not the
        # single condition_attr_id/condition_value pair. As long
        # as the rule's ACTION is declarative (handled below),
        # gate it via condition_script instead of dropping it —
        # apply time runs the same Tier-1/Tier-2 boolean
        # evaluator apply_hiding_rules already uses (D2 "never
        # guess" still holds: unknown outcome never fires).
        condition_script = scripts.get(fn_id)
        if not condition_script:
            state.cond_script_skipped += 1
            logger.warning(
                "cpq: rule %r references condition_function_id=%d "
                "but no BmFunction script was found — not gated",
                rule_name, fn_id)
            return SKIP_ROW
        cond_attr_id, cond_value, cond_operator = 0, "", "4"
    else:
        if not inp_list:
            return SKIP_ROW
        cond_attr_id, cond_value, cond_operator = inp_list[-1]

    # Amendment 12 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
    # a message-only action (function_id=-1, empty value1, but
    # a real human-authored `comments` string) is neither a
    # hide, a set, nor a restrict — its only content is a
    # warning to show when this rule's own condition (script OR
    # declarative) fires. Originally scoped to condition_script
    # only ("a declarative-condition version would need
    # separate confirmation before being added here" — this
    # comment's own prior text); docs/CPQ_CONDITIONAL_REQUIRED_
    # RULE_PLAN_2026_08_05.md provides that confirmation via a
    # 4-catalog audit (138/150 real declarative "set_type=-1,
    # no value1" rows carry a genuine message). By this point
    # either condition_script is set or inp_list was non-empty
    # (the `if not inp_list: continue` above already filtered
    # out rules with neither), so no extra guard is needed here.
    # docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md
    # — a declarative (non-script) condition where the SAME
    # attribute is checked with 2+ different operators cannot
    # yet be evaluated correctly (evaluate_declarative_
    # conditions collapses to the first row's operator+value,
    # silently dropping the rest). Confirmed catalog-wide that
    # no single combining rule is safe for every such shape
    # yet (80 real rules across 4 catalogs, only 76% resolved
    # with confidence) — applies uniformly to EVERY rule type
    # built from this same inp_list (constraint, recommend,
    # value-less-hide, validation-message below), not just the
    # newest one: a HidingRule/ConstraintRule/RecommendationRule
    # with this exact same-attribute/multi-operator shape would
    # evaluate its condition just as incorrectly (e.g.
    # collapsing "< 1 OR > 12" to only ever check "< 1", or
    # merging a CONTAINS/NOT-CONTAINS pair into a single
    # over-broad OR) as an unguarded declarative ValidationRule
    # would. Skip all four entirely rather than load any of
    # them with a guessed combining rule. Does not apply to
    # script-gated rules (condition_script is not None) —
    # those are unaffected, evaluated by the BML engine, not
    # evaluate_declarative_conditions.
    declarative_condition_collision = (
        condition_script is None
        and inp_list is not None
        and engine._condition_has_operator_collision(inp_list)
    )
    return condition_script, cond_attr_id, cond_value, cond_operator, declarative_condition_collision
