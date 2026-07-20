"""Deterministic, rule-focused scenario generation for CPQ catalogs."""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable

from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, RecommendationRule
from aryx.cpq.validation.models import Scenario
from aryx.cpq.validation.scenario_support import (
    append_scenario, attribute_index, first_non_match, place_value, rule_key,
    split_values,
)

Rule = HidingRule | RecommendationRule | ConstraintRule
_SCRIPT_LITERAL_RE = re.compile(r'(\w+)\s*(?:==|!=|<>)\s*"([^"]*)"')


def generate_scenarios(
    attrs: list[ConfigAttr],
    hiding_rules: list[HidingRule],
    rec_rules: list[RecommendationRule],
    con_rules: list[ConstraintRule],
    *,
    max_scenarios: int = 10_000,
) -> list[Scenario]:
    """Cover every menu option and every discoverable rule-condition branch."""
    ordered_attrs = sorted(attrs, key=lambda attr: (attr.order, attr.entity_id))
    by_id = attribute_index(ordered_attrs)
    scenarios: list[Scenario] = []
    seen: set[tuple[object, ...]] = set()
    append_scenario(scenarios, seen, "baseline", {}, max_scenarios)
    for attr in ordered_attrs:
        for option in sorted(attr.options, key=lambda item: (item.order, item.item_value)):
            filled: dict[str, str] = {}
            multi: dict[str, tuple[str, ...]] = {}
            place_value(attr, option.item_value, filled, multi)
            append_scenario(
                scenarios, seen, f"option:{attr.variable_name}:{option.item_value}",
                filled, max_scenarios, multi,
            )
    rules: Iterable[Rule] = sorted(
        (*hiding_rules, *rec_rules, *con_rules), key=rule_key,
    )
    for ordinal, rule in enumerate(rules):
        _add_rule_scenarios(scenarios, seen, rule, ordinal, by_id, max_scenarios)
    return scenarios


def _add_rule_scenarios(
    scenarios: list[Scenario],
    seen: set[tuple[object, ...]],
    rule: Rule,
    ordinal: int,
    by_id: dict[int, ConfigAttr],
    limit: int,
) -> None:
    """Add true, alternate-OR, false, and script-literal cases for one rule."""
    grouped: dict[int, list[str]] = defaultdict(list)
    for attribute_id, encoded in _condition_pairs(rule):
        grouped[attribute_id].extend(split_values(encoded))
    seed: dict[str, str] = {}
    seed_multi: dict[str, tuple[str, ...]] = {}
    for attribute_id, values in sorted(grouped.items()):
        attr = by_id.get(attribute_id)
        if attr and values:
            place_value(attr, values[0], seed, seed_multi)
    if seed or seed_multi:
        append_scenario(scenarios, seen, f"rule:{ordinal}:true", seed, limit, seed_multi)
    for attribute_id, values in sorted(grouped.items()):
        attr = by_id.get(attribute_id)
        if not attr:
            continue
        for value in values:
            variant = dict(seed)
            variant_multi = dict(seed_multi)
            place_value(attr, value, variant, variant_multi)
            append_scenario(
                scenarios, seen, f"rule:{ordinal}:or:{value}", variant, limit, variant_multi,
            )
        non_match = first_non_match(attr, values)
        if non_match is not None:
            variant = dict(seed)
            variant_multi = dict(seed_multi)
            place_value(attr, non_match, variant, variant_multi)
            append_scenario(
                scenarios, seen, f"rule:{ordinal}:false", variant, limit, variant_multi,
            )
    _add_script_scenarios(scenarios, seen, rule, ordinal, by_id, limit)


def _add_script_scenarios(
    scenarios: list[Scenario], seen: set[tuple[object, ...]], rule: Rule,
    ordinal: int, by_id: dict[int, ConfigAttr], limit: int,
) -> None:
    """Add independently discoverable BML comparison literal cases."""
    for variable, value in _script_literals(rule):
        script_filled: dict[str, str] = {}
        script_multi: dict[str, tuple[str, ...]] = {}
        attr = next((item for item in by_id.values() if item.variable_name == variable), None)
        if attr is None:
            script_filled[variable] = value
        else:
            place_value(attr, value, script_filled, script_multi)
        append_scenario(
            scenarios, seen, f"rule:{ordinal}:script:{variable}:{value}",
            script_filled, limit, script_multi,
        )


def _condition_pairs(rule: Rule) -> list[tuple[int, str]]:
    """Return declarative conditions, excluding script-only actions."""
    if rule.script or getattr(rule, "condition_script", None):
        return []
    return list(rule.conditions or [(rule.condition_attr_id, rule.condition_value)])


def _script_literals(rule: Rule) -> list[tuple[str, str]]:
    """Harvest comparison literals without executing BML."""
    scripts = [rule.script, getattr(rule, "condition_script", None)]
    return sorted({
        pair for script in scripts if script
        for pair in _SCRIPT_LITERAL_RE.findall(script)
    })
