"""``apply_validation_rules`` -- evaluate Amendment 12 warning-message
rules against the current filled state (Phase 4 step 6 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Stateless and purely functional -- no ``CpqEngine`` instance needed; same
``attr_index`` helpers as ``apply_recommendation_rules``.
"""

from __future__ import annotations

from aryx.cpq.bml.bml import BmlEvaluator, evaluate_declarative_conditions
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.state import ConfigAttr, ValidationRule


def apply_validation_rules(
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    rules: list[ValidationRule],
    bml_eval: BmlEvaluator | None = None,
    filled_multi: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """Evaluate every ValidationRule's condition (script OR
    declarative — docs/CPQ_CONDITIONAL_REQUIRED_RULE_PLAN_2026_08_05.md)
    against the current filled state (Amendment 12). Returns
    {variable_name: message} for every rule whose condition currently,
    definitely holds — never on False or unknown (D2 "never guess": an
    unresolvable condition never fires a warning it can't actually
    back).

    Script-backed rules need bml_eval; bml_eval=None skips those only
    (same convention as apply_recommendation_rules/
    apply_constraint_rules) — declarative rules need no BML evaluator
    at all and are unaffected by bml_eval=None, same as
    apply_hiding_rules' own declarative branch.

    filled_multi — see apply_hiding_rules; only consulted for
    declarative conditions on a select_type=="multi" attribute.
    """
    if not rules:
        return {}
    by_id = _attr_index(attrs)
    filled_by_rule_id = _filled_by_rule_id(attrs, filled, filled_multi)
    warnings: dict[str, str] = {}
    for rule in rules:
        target = by_id.get(rule.target_attr_id)
        if not target:
            continue
        if rule.condition_script is not None:
            if bml_eval is None:
                continue
            if bml_eval.condition_holds(rule.condition_script, filled) is True:
                warnings[target.variable_name] = rule.message
        elif rule.conditions:
            matched, _blocked = evaluate_declarative_conditions(
                rule.conditions, filled_by_rule_id)
            if matched is True:
                warnings[target.variable_name] = rule.message
    return warnings
