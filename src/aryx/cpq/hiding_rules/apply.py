"""``apply_hiding_rules`` -- evaluate loaded hiding rules against the
current filled values (Phase 4 step 4 extraction from ``cpq/engine.py``,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless and purely functional -- no ``CpqEngine`` instance needed; its
two former ``self.`` helpers are the plain functions in this same
package.
"""

from __future__ import annotations

from aryx.cpq import rule_trace
from aryx.cpq.bml.bml import BmlEvaluator, evaluate_declarative_conditions
from aryx.cpq.engine import _condition_value_matches
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.state import ConfigAttr, HidingRule


def apply_hiding_rules(
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    rules: list[HidingRule],
    bml_eval: BmlEvaluator | None = None,
    filled_multi: dict[str, list[str]] | None = None,
) -> tuple[list[ConfigAttr], list[str], set[str]]:
    """Apply hiding rules against current filled values.

    Script-backed rules (rule.script set) derive their hide/show outcome
    from the BML evaluator using the current filled variables (keyed by
    variable_name — BML scripts compare variable names directly, same
    convention as apply_constraint_rules). An unknown script outcome
    (bml_eval is None, or the evaluator can't determine it yet) leaves
    the target visible rather than risking hiding something the
    customer still needs — the safe default mirrors constraints'
    "unknown applies no constraint" rule, just inverted for hiding
    (unknown → don't hide, not → hide everything).

    filled_multi — select_type=="multi" attrs' current selections (see
    _filled_by_rule_id); only consulted for declarative conditions
    (operators "7"/"8"). Script-backed rules are unaffected — they
    already read `filled` directly via bml_eval, a separate contract.

    Returns:
      filtered_attrs — attrs still visible after rules are applied
      rule_messages  — human-readable list of rules that fired (for reporting)
      hidden_vns     — variable_names explicitly hidden by a fired rule
    """
    if not rules:
        return attrs, [], set()

    by_rule_id = _attr_index(attrs)
    filled_by_rule_id = _filled_by_rule_id(attrs, filled, filled_multi)

    hidden_eids: set[int] = set()
    messages: list[str] = []

    for rule in rules:
        target = by_rule_id.get(rule.target_attr_id)
        if not target:
            continue
        if rule.script is not None:
            if bml_eval is None:
                continue
            hide = bml_eval.hide_for_script(rule.script, filled)
            if hide is True:
                hidden_eids.add(target.entity_id)
                messages.append(
                    f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                )
                rule_trace.record_fire(
                    rule_type="hiding", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome="hide", bml_tier="script",
                )
            elif hide is False:
                hidden_eids.discard(target.entity_id)
                rule_trace.record_fire(
                    rule_type="hiding", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome="show", bml_tier="script",
                )
            continue
        if rule.conditions:
            matched, _blocked = evaluate_declarative_conditions(
                rule.conditions, filled_by_rule_id)
            if matched is not True:
                continue  # unresolved or definitively false — doesn't fire
        else:
            current_val = filled_by_rule_id.get(rule.condition_attr_id)
            if current_val is None:
                continue  # condition attr not filled yet — rule doesn't fire
            if not _condition_value_matches(
                current_val, rule.condition_value, rule.condition_operator
            ):
                continue
        if rule.hide:
            hidden_eids.add(target.entity_id)
            messages.append(
                f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
            )
            rule_trace.record_fire(
                rule_type="hiding", rule_id=rule.rule_name,
                attr=target.variable_name, outcome="hide",
            )
        else:
            hidden_eids.discard(target.entity_id)
            rule_trace.record_fire(
                rule_type="hiding", rule_id=rule.rule_name,
                attr=target.variable_name, outcome="show",
            )

    hidden_vns = {a.variable_name for a in attrs if a.entity_id in hidden_eids}
    filtered = [a for a in attrs if a.entity_id not in hidden_eids]
    return filtered, messages, hidden_vns
