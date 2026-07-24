"""Read-only adapter that captures the production CPQ loop for comparison."""
from __future__ import annotations

from typing import Any

from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, RecommendationRule
from aryx.cpq.validation.compare import ProductionState
from aryx.cpq.validation.models import Scenario


def evaluate_production(
    engine: Any,
    attrs: list[ConfigAttr],
    scenario: Scenario,
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
    bml_eval: Any,
) -> ProductionState:
    """Run the existing engine against copies and capture its observable state."""
    sources = dict(scenario.sources)
    filled_multi = {
        key: list(values) for key, values in scenario.filled_multi.items()
    }
    visible, filled, _display, constrained = engine.evaluate_rules_loop(
        list(attrs), {}, dict(scenario.filled), hiding_rules, rec_rules, con_rules,
        bml_eval=bml_eval, filled_source=sources, filled_multi=filled_multi,
    )
    governed = engine.governed_target_ids(visible, hiding_rules, rec_rules, con_rules)
    rule_governed = engine.rule_governed_ids(visible, hiding_rules, rec_rules, con_rules)
    _filled, _display, pending = engine.auto_fill(
        visible, {}, already_filled=filled, constrained_opts=constrained,
        filled_source=sources, governed_ids=governed,
        already_filled_multi=filled_multi, rule_governed_ids=rule_governed,
    )
    by_entity_id = {attr.entity_id: attr.variable_name for attr in attrs}
    constraints = {
        by_entity_id[entity_id]: tuple(values)
        for entity_id, values in sorted(constrained.items())
        if entity_id in by_entity_id
    }
    return ProductionState(
        filled=dict(sorted(filled.items())),
        visible=frozenset(attr.variable_name for attr in visible),
        constraints=constraints,
        pending=tuple(sorted(attr.variable_name for attr in pending)),
        filled_multi={
            key: tuple(values) for key, values in sorted(filled_multi.items())
        },
    )
