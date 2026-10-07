"""Independent attribute resolution and declarative condition semantics."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from aryx.cpq.bml.bml_declarative import _MULTI_SELECT_OPERATORS, _operator_hit
from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, RecommendationRule
from aryx.cpq.validation.models import ValidationIssue
from aryx.cpq.validation.script_oracle import DeterministicBmlOracle

Rule = HidingRule | RecommendationRule | ConstraintRule


class ConditionEvaluator:
    """Resolve rule targets and evaluate AND-of-OR declarative conditions."""

    def __init__(
        self, attrs: tuple[ConfigAttr, ...], scripts: DeterministicBmlOracle,
    ) -> None:
        """Build immutable rule-ID and deterministic-script lookup state."""
        self.scripts = scripts
        self.by_id = self._attribute_index(attrs)

    def status(
        self, rule: Rule, filled: dict[str, str],
        filled_multi: dict[str, tuple[str, ...]] | None = None,
    ) -> bool | None:
        """Return true, false, or unknown for one rule condition."""
        condition_script = getattr(rule, "condition_script", None)
        if condition_script:
            multi = filled_multi or {}
            variables = {
                **filled,
                **{key: "~".join(values) for key, values in multi.items()},
            }
            return self.scripts.condition(condition_script, variables)
        pairs = rule.conditions or [(rule.condition_attr_id, rule.condition_value, "4")]
        grouped: dict[int, list[str]] = defaultdict(list)
        operator_by_attr: dict[int, str] = {}
        for attribute_id, value, operator in pairs:
            if attribute_id not in operator_by_attr:
                operator_by_attr[attribute_id] = operator
            grouped[attribute_id].append(value)
        saw_unknown = False
        for attribute_id, values in grouped.items():
            attribute = self.by_id.get(attribute_id)
            variable = attribute.variable_name if attribute else ""
            actual_values = (
                (filled[variable],) if variable in filled
                else (filled_multi or {}).get(variable, ())
            )
            if not actual_values:
                saw_unknown = True
                continue
            operator = operator_by_attr[attribute_id]
            # "7"/"8" are defined on the WHOLE current-selection set (per
            # _operator_hit's docstring), not per selected value -- e.g.
            # "8" (disjoint from) must see {L1, ADDON} as one set to know
            # it intersects, rather than OR-ing per-value hits, which would
            # wrongly fire on the ADDON value alone even though the set as
            # a whole isn't disjoint.
            if operator in _MULTI_SELECT_OPERATORS:
                hits = [_operator_hit("~".join(actual_values), values, operator)]
            else:
                hits = [_operator_hit(actual, values, operator) for actual in actual_values]
            if any(hit is True for hit in hits):
                continue
            if all(hit is False for hit in hits):
                return False
            saw_unknown = True  # unresolved (e.g. unparseable numeric) -- never guessed
        if saw_unknown:
            return None
        return True

    def target(self, rule: Rule, issues: list[ValidationIssue]) -> ConfigAttr | None:
        """Resolve a target through source or entity ID and report failures."""
        target = self.by_id.get(rule.target_attr_id)
        if target is None:
            issues.append(ValidationIssue(
                "missing_target", "rule target does not resolve to an attribute",
                rule=rule.rule_name,
            ))
        return target

    @staticmethod
    def _attribute_index(attrs: tuple[ConfigAttr, ...]) -> dict[int, ConfigAttr]:
        """Index attributes by both Aryx entity and source-native IDs."""
        index = {attr.entity_id: attr for attr in attrs}
        index.update({attr.source_id: attr for attr in attrs if attr.source_id is not None})
        return index


def rule_key(rule: Any) -> tuple[str, int, int, str]:
    """Return a stable ordering key independent of database row order."""
    return (rule.rule_name, rule.target_attr_id, rule.condition_attr_id, rule.condition_value)
