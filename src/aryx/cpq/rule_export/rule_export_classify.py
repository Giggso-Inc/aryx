"""Per-rule scope classification against the product tree.

Split out of `cpq/rule_export.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

from typing import Any

from aryx.cpq.rule_export.rule_export_tree import TreeNode, _leaf_names, _normalize
from aryx.cpq.state import ConstraintRule, HidingRule, RecommendationRule

UNSCOPED = "unscoped_or_unresolved"


def _rule_condition_values(rule: Any) -> list[str] | None:
    """Literal, staticallly-known condition values for a declarative rule.

    Returns None (not []) for script-backed rules -- those are NEVER
    statically classified (export is static, not a BML simulation), always
    landing in UNSCOPED. Returns [] for a rule with no product-relevant
    condition at all (also UNSCOPED, but distinctly "nothing to match").
    """
    if getattr(rule, "script", None) is not None:
        return None
    if getattr(rule, "condition_script", None) is not None:
        return None
    conditions = getattr(rule, "conditions", None)
    if conditions:
        return [v for _attr_id, v, _operator in conditions]
    condition_value = getattr(rule, "condition_value", "") or ""
    return [condition_value] if condition_value else []


def classify_rule_scope(rule: Any, name_index: dict[str, TreeNode]) -> dict[str, Any]:
    """Return {"family": ..., "product_line": ..., "model": ...} for the
    FIRST tree node one of the rule's condition values exactly matches
    (case/whitespace-normalized), expanded to cover descendant models when
    the match lands on a family/line node -- or {"scope": UNSCOPED}."""
    values = _rule_condition_values(rule)
    if not values:
        return {"scope": UNSCOPED}
    for value in values:
        node = name_index.get(_normalize(value))
        if node is not None:
            return {
                "matched_node": node.name,
                "covers_models": _leaf_names(node),
            }
    return {"scope": UNSCOPED}


def _rule_dict(rule: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "rule_name": rule.rule_name,
        "target_attr_id": rule.target_attr_id,
        "condition_attr_id": getattr(rule, "condition_attr_id", None),
        "condition_value": getattr(rule, "condition_value", None),
        "conditions": getattr(rule, "conditions", None),
        "script": getattr(rule, "script", None),
        "condition_script": getattr(rule, "condition_script", None),
    }
    if isinstance(rule, HidingRule):
        d["rule_type"] = "hiding"
        d["hide"] = rule.hide
    elif isinstance(rule, RecommendationRule):
        d["rule_type"] = "recommendation"
        d["recommended_value"] = rule.recommended_value
    elif isinstance(rule, ConstraintRule):
        d["rule_type"] = "constraint"
        d["allowed_values"] = rule.allowed_values
    return d
