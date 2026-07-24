"""Independent attribute resolution and declarative condition semantics."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

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
        pairs = rule.conditions or [(rule.condition_attr_id, rule.condition_value)]
        grouped: dict[int, list[str]] = defaultdict(list)
        for attribute_id, value in pairs:
            grouped[attribute_id].append(value)
        for attribute_id, values in grouped.items():
            attribute = self.by_id.get(attribute_id)
            variable = attribute.variable_name if attribute else ""
            actual_values = (
                (filled[variable],) if variable in filled
                else (filled_multi or {}).get(variable, ())
            )
            if not actual_values:
                return None
            if not any(matches(actual, value) for actual in actual_values for value in values):
                return False
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


def matches(actual: str, expected: str) -> bool:
    """Match a literal or tilde-delimited OR list case-insensitively."""
    allowed = {value.strip().lower() for value in expected.split("~") if value.strip()}
    return actual.strip().lower() in allowed


def rule_key(rule: Any) -> tuple[str, int, int, str]:
    """Return a stable ordering key independent of database row order."""
    return (rule.rule_name, rule.target_attr_id, rule.condition_attr_id, rule.condition_value)
