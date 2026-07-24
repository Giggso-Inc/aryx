"""Independent declarative oracle for CPQ rule semantics.

"Oracle" means reference results here; this module has no Oracle Database
dependency and never calls the production engine's ``apply_*`` methods.
"""
from __future__ import annotations

from collections import defaultdict

from aryx.cpq.state import ConfigAttr, ConstraintRule, HidingRule, RecommendationRule
from aryx.cpq.validation.conditions import ConditionEvaluator, rule_key
from aryx.cpq.validation.constraint_phase import evaluate_constraints
from aryx.cpq.validation.models import RuleEvaluation, ValidationIssue
from aryx.cpq.validation.script_oracle import DeterministicBmlOracle


class DeterministicRuleOracle:
    """Evaluate rule actions from immutable catalog inputs in stable order."""

    def __init__(
        self,
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
        scripts: DeterministicBmlOracle | None = None,
    ) -> None:
        """Build immutable, stably ordered rule and attribute indexes."""
        self.attrs = tuple(sorted(attrs, key=lambda attr: (attr.order, attr.entity_id)))
        self.hiding_rules = tuple(sorted(hiding_rules, key=rule_key))
        self.rec_rules = tuple(sorted(rec_rules, key=rule_key))
        self.con_rules = tuple(sorted(con_rules, key=rule_key))
        self.scripts = scripts or DeterministicBmlOracle()
        self.conditions = ConditionEvaluator(self.attrs, self.scripts)

    def evaluate_rules(
        self, filled: dict[str, str],
        filled_multi: dict[str, tuple[str, ...]] | None = None,
    ) -> RuleEvaluation:
        """Evaluate hide, recommendation, and constraint phases independently."""
        multi = filled_multi or {}
        variables = {**filled, **{key: "~".join(values) for key, values in multi.items()}}
        hidden, hide_unknown, hide_issues = self._evaluate_hiding(filled, multi, variables)
        recommendations, rec_unknown, rec_issues = self._evaluate_recommendations(
            filled, multi, variables,
        )
        constraints, con_unknown, con_issues = evaluate_constraints(
            self.con_rules, self.conditions, self.scripts, filled, multi, variables,
        )
        return RuleEvaluation(
            hidden=frozenset(hidden),
            recommendations=recommendations,
            constraints=constraints,
            unknown_rules=tuple(sorted(hide_unknown | rec_unknown | con_unknown)),
            issues=tuple(sorted((*hide_issues, *rec_issues, *con_issues))),
        )

    def _evaluate_hiding(
        self, filled: dict[str, str], filled_multi: dict[str, tuple[str, ...]],
        variables: dict[str, str],
    ) -> tuple[set[str], set[str], list[ValidationIssue]]:
        """Aggregate active hide/show actions without list-order precedence."""
        actions: dict[str, list[tuple[bool, str]]] = defaultdict(list)
        unknown: set[str] = set()
        issues: list[ValidationIssue] = []
        for rule in self.hiding_rules:
            target = self.conditions.target(rule, issues)
            if target is None:
                continue
            active = (
                self.scripts.hide(rule.script, variables)
                if rule.script else self.conditions.status(rule, filled, filled_multi)
            )
            if active is None and rule.script and not self.scripts.supports_hide(rule.script):
                unknown.add(rule.rule_name)
            elif active:
                actions[target.variable_name].append((rule.hide, rule.rule_name))
        hidden: set[str] = set()
        for variable, target_actions in sorted(actions.items()):
            action_values = {action for action, _name in target_actions}
            if True in action_values:
                hidden.add(variable)
            if len(action_values) > 1:
                names = ", ".join(sorted(name for _action, name in target_actions))
                issues.append(ValidationIssue(
                    "visibility_conflict", f"simultaneous hide/show rules: {names}", variable,
                ))
        return hidden, unknown, issues

    def _evaluate_recommendations(
        self, filled: dict[str, str], filled_multi: dict[str, tuple[str, ...]],
        variables: dict[str, str],
    ) -> tuple[dict[str, str], set[str], list[ValidationIssue]]:
        """Aggregate active recommendation values and report conflicts."""
        proposals: dict[str, list[tuple[str, str]]] = defaultdict(list)
        unknown: set[str] = set()
        issues: list[ValidationIssue] = []
        for rule in self.rec_rules:
            target = self.conditions.target(rule, issues)
            if target is None:
                continue
            if rule.script:
                values = self.scripts.values(rule.script, variables)
                if values is None or len(values) != 1:
                    if not self.scripts.supports_values(rule.script):
                        unknown.add(rule.rule_name)
                    continue
                value = values[0]
            else:
                active = self.conditions.status(rule, filled, filled_multi)
                if (active is None and rule.condition_script
                        and not self.scripts.supports_condition(rule.condition_script)):
                    unknown.add(rule.rule_name)
                    continue
                if not active:
                    continue
                value = rule.recommended_value
            proposals[target.variable_name].append((value, rule.rule_name))
        recommendations: dict[str, str] = {}
        for variable, values_and_names in sorted(proposals.items()):
            values = {value for value, _name in values_and_names}
            if len(values) == 1:
                recommendations[variable] = next(iter(values))
            else:
                issues.append(ValidationIssue(
                    "recommendation_conflict", "active recommendations disagree", variable,
                    rule=", ".join(sorted(name for _value, name in values_and_names)),
                ))
        return recommendations, unknown, issues
