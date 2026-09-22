"""``find_rule_inconsistencies`` -- the read-only cross-check of `filled`
against each rule type's own independently recomputed result (Phase 4
step 6 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Takes the ``engine`` instance: the whole point of the check is to re-run
``apply_hiding_rules``/``apply_constraint_rules`` through the SAME engine
the payload was built with (both are routinely replaced per-instance by
tests, and ``apply_constraint_rules`` is deliberately still a real
``CpqEngine`` method awaiting its own decomposition).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq.bml.bml import BmlEvaluator, evaluate_declarative_conditions
from aryx.cpq.engine import _condition_value_matches
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, HidingRule, RecommendationRule,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.engine import CpqEngine


def find_rule_inconsistencies(
    engine: CpqEngine,
    filled: dict[str, str],
    attrs: list[ConfigAttr],
    hiding_rules: list[HidingRule],
    con_rules: list[ConstraintRule],
    rec_rules: list[RecommendationRule],
    bml_eval: BmlEvaluator | None = None,
    filled_source: dict[str, str] | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
) -> list[dict[str, Any]]:
    """Cross-check `filled` against each rule type's OWN independently
    computed result — NOT a self-referential re-derivation of the same
    data that produced `filled` in the first place (see
    docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §1 for why a check
    against attr_by_vn/options would be tautological and useless).

    Three checks, one per rule type — all reuse the SAME apply_* methods
    already used to build the payload, so BML-script-backed rules
    (rule.script / rule.condition_script) are covered automatically,
    with zero new script-evaluation code (§4's docstring):

      - hiding:         attr is filled AND an active hiding rule matches
                         it right now — it should never have been kept.
      - constraint:     attr's filled value is not in the currently
                         active allowed-values set for it (stale/
                         pre-cascade value that should have been cleared).
      - recommendation: attr not filled via "user" source, whose
                         recommendation rule condition IS satisfied, but
                         the filled value does not match recommended_value
                         (confirmed live this session: the "invalidated —
                         re-evaluating" cascade note that changes nothing).

    Returns a list of {"attr", "value", "rule_type", "issue"} dicts —
    empty when everything is consistent. Never raises; a rule whose
    script outcome is "unknown" is simply skipped for that check (never
    guess a bug that isn't there).
    """
    issues: list[dict[str, Any]] = []
    by_vn = {a.variable_name: a for a in attrs}

    _visible, _msgs, hidden_vns = engine.apply_hiding_rules(
        attrs, filled, hiding_rules, bml_eval, filled_multi=filled_multi,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix)
    for vn in hidden_vns:
        if filled.get(vn):
            issues.append({
                "attr": vn, "value": filled[vn], "rule_type": "hiding",
                "issue": "filled but an active hiding rule matches",
            })

    constrained_opts = engine.apply_constraint_rules(
        attrs, con_rules, filled, bml_eval, filled_multi=filled_multi,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix)
    for vn, value in filled.items():
        attr = by_vn.get(vn)
        allowed = constrained_opts.get(attr.entity_id) if attr else None
        if allowed is not None and value not in allowed:
            issues.append({
                "attr": vn, "value": value, "rule_type": "constraint",
                "issue": f"value not in active allowed set {allowed}",
            })

    by_rule_id = _attr_index(attrs)
    filled_by_rule_id = _filled_by_rule_id(attrs, filled, filled_multi)
    for rule in rec_rules:
        target = by_rule_id.get(rule.target_attr_id)
        if not target or target.variable_name not in filled:
            continue
        vn = target.variable_name
        if filled_source and filled_source.get(vn) == "user":
            # A customer's deliberate override is not an inconsistency
            # even if it now disagrees with a currently-satisfied
            # recommendation — see docstring's "not filled via 'user'
            # source" contract, which this param actually enforces.
            continue
        condition_met: bool | None
        if rule.script is not None:
            if bml_eval is None:
                continue
            allowed = bml_eval.allowed_values_for_script(rule.script, filled)
            condition_met = bool(allowed) and len(allowed) == 1
            recommended = allowed[0] if condition_met else None
        elif rule.condition_script is not None:
            if bml_eval is None:
                continue
            condition_met = bml_eval.condition_holds(rule.condition_script, filled) is True
            recommended = rule.recommended_value
        else:
            if rule.conditions:
                matched, _blocked = evaluate_declarative_conditions(
                    rule.conditions, filled_by_rule_id)
                condition_met = matched is True
            else:
                current_val = filled_by_rule_id.get(rule.condition_attr_id)
                condition_met = (
                    current_val is not None
                    and _condition_value_matches(
                        current_val, rule.condition_value, rule.condition_operator
                    )
                )
            recommended = rule.recommended_value
        if condition_met and recommended is not None and filled[vn].lower() != recommended.lower():
            issues.append({
                "attr": vn, "value": filled[vn], "rule_type": "recommendation",
                "issue": f"condition met but value != recommended '{recommended}'",
            })

    return issues
