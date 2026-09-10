"""``resolve_recommended_value`` -- "does this recommendation rule fire
right now, and with what value" (Phase 4 step 6 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Lifted verbatim (branch for branch) out of the identical condition/value
resolution ``apply_recommendation_rules`` and
``resync_stale_recommendations`` each carried inline, so the two passes
cannot drift apart -- the dual-script gating gap fixed in 2026-08-25 had
to be fixed twice precisely because this logic was duplicated.
"""

from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator, evaluate_declarative_conditions
from aryx.cpq.engine import _condition_value_matches
from aryx.cpq.state import RecommendationRule


def resolve_recommended_value(
    rule: RecommendationRule,
    filled: dict[str, str],
    filled_by_rule_id: dict[int, str],
    bml_eval: BmlEvaluator | None,
) -> str | None:
    """The value `rule` currently recommends, or None when it doesn't fire.

    None covers every "doesn't fire" case uniformly — condition False,
    condition unknown, a script-backed action resolving to zero or 2+
    candidates, or a script-backed rule with no evaluator available
    (bml_eval=None, the caller's opt-out). D2 "never guess": unknown is
    always None, never an assumed value. `RecommendationRule.
    recommended_value` is itself a plain ``str`` (default "", never
    None), so None is an unambiguous sentinel here.
    """
    if rule.script is not None:
        if bml_eval is None:
            return None
        # Live-confirmed gap (2026-08-25, SVX "Force Set Quantity of
        # Body Worn Cameras with sum of Mounting"): a rule can carry
        # a script-backed ACTION and a script-backed CONDITION at
        # the same time -- the action alone says nothing about WHEN
        # to fire. Gate on the condition first when present, same
        # D2 "never guess" convention as the declarative branch
        # below (unknown/False -> never fires).
        if rule.condition_script is not None:
            if bml_eval.condition_holds(rule.condition_script, filled) is not True:
                return None
        allowed = bml_eval.allowed_values_for_script(rule.script, filled)
        if not allowed or len(allowed) != 1:
            return None  # unknown, or ambiguous — never guess
        return allowed[0]
    if rule.condition_script is not None:
        if bml_eval is None:
            return None
        fires = bml_eval.condition_holds(rule.condition_script, filled)
        if fires is not True:
            return None  # False or unknown — never guess, doesn't fire
        return rule.recommended_value
    if rule.conditions:
        matched, _blocked = evaluate_declarative_conditions(
            rule.conditions, filled_by_rule_id)
        if matched is not True:
            return None
    else:
        if rule.condition_attr_id not in filled_by_rule_id:
            return None
        if not _condition_value_matches(
            filled_by_rule_id[rule.condition_attr_id], rule.condition_value,
            rule.condition_operator,
        ):
            return None
    return rule.recommended_value
