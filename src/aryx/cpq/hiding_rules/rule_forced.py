"""`_is_mandatory_input_attr`'s recommendation-rule-driven active-source
widening (Phase 4 step 4 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless and purely functional -- no ``CpqEngine`` instance needed.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.hiding_rules.attr_index import _attr_index
from aryx.cpq.state import ConfigAttr, RecommendationRule


def _rule_forced_from_active_decision_vns(
    rules: list[Any] | None, attrs: list[ConfigAttr] | None,
    filled_source: dict[str, str], active_sources: frozenset[str],
) -> frozenset[str]:
    """`_is_mandatory_input_attr`'s `rule_forced_active_vns` — variable_
    names a RecommendationRule set via a SINGLE declarative condition
    (script/condition_script/multi-input `conditions` rules abstain --
    no one extractable trigger attr to check) whose trigger attr is
    itself actively sourced. Catalog-agnostic: walks `RecommendationRule.
    condition_attr_id`/`target_attr_id` generically, no attribute or
    rule name hardcoded -- see `_is_mandatory_input_attr`'s own
    docstring for the live case (wirelessCarrier_astro forced by
    "...when ATAK is enabled") this closes.
    """
    if not rules or not attrs:
        return frozenset()
    attr_idx = _attr_index(attrs)
    result: set[str] = set()
    for rule in rules:
        if not isinstance(rule, RecommendationRule):
            continue
        if rule.script is not None or rule.condition_script is not None:
            continue  # no single extractable trigger attr -- never guess
        if rule.conditions:
            continue  # multi-input AND/OR -- ambiguous which leg to trust
        cond_attr = attr_idx.get(rule.condition_attr_id)
        target_attr = attr_idx.get(rule.target_attr_id)
        if cond_attr is None or target_attr is None:
            continue
        if filled_source.get(cond_attr.variable_name) in active_sources:
            result.add(target_attr.variable_name)
    return frozenset(result)
