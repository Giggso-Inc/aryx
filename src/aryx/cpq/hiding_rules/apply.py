"""``apply_hiding_rules`` -- evaluate loaded hiding rules against the
current filled values (Phase 4 step 4 extraction from ``cpq/engine.py``,
see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless and purely functional -- no ``CpqEngine`` instance needed; its
two former ``self.`` helpers are the plain functions in this same
package.
"""

from __future__ import annotations

import time

from aryx.cpq.rule_trace import rule_trace
from aryx.cpq.bml.bml import BmlEvaluator, evaluate_declarative_conditions
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.engine import _condition_value_matches, logger
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id
from aryx.cpq.hiding_rules.master_string import hide_with_master_string
from aryx.cpq.hiding_rules.master_writers import master_hide_enabled
from aryx.cpq.hiding_rules.unknown_log import log_unknown_script_hide
from aryx.cpq.state import ConfigAttr, HidingRule


def apply_hiding_rules(
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    rules: list[HidingRule],
    bml_eval: BmlEvaluator | None = None,
    filled_multi: dict[str, list[str]] | None = None,
    workspace_id: int | None = None,
    catalog_prefix: str = "",
    dt_cache: dict[tuple[int, str], tuple] | None = None,
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

    workspace_id/catalog_prefix/dt_cache — only consulted for rules with
    dt_whitelist_substitute=True (see that field's own docstring and
    hiding_rules.type11._DT_WHITELIST_SUBSTITUTE_HIDING_RULE_NAMES);
    `None`/default keeps every existing caller's behavior unchanged,
    including for such rules (no workspace_id means "can't check the
    Data Table," which falls back to the same "leave visible" safe
    default as an unknown script outcome — never hides more aggressively
    for lack of context).

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
    _t0 = time.monotonic()
    _script_s = 0.0
    _outcomes = {"hide": 0, "show": 0, "unknown": 0}

    for rule in rules:
        target = by_rule_id.get(rule.target_attr_id)
        if not target:
            continue
        if rule.dt_whitelist_substitute:
            # Missing-script substitute (see HidingRule.dt_whitelist_
            # substitute's own docstring): hide only when a real,
            # ingested constraint-shaped Data Table row CONFIRMS no
            # legal value exists for this attr right now (resolve_
            # whitelist_values returns [], never None -- None means "no
            # Data Table coverage at all," which must NOT be treated as
            # "confirmed no value," same never-guess distinction that
            # function's own docstring already establishes).
            if workspace_id is not None:
                # Lazy import (both names): aryx.cpq.engine imports the
                # `hiding_rules` package at module scope before
                # `_cpq_model_candidates` is defined further down in
                # engine.py -- a top-level import here would be a
                # circular-import ordering error. `dt_resolve_whitelist_
                # values` is looked up here too, not bound at module
                # scope, so a test's `monkeypatch.setattr("aryx.cpq.
                # engine.dt_resolve_whitelist_values", ...)` is actually
                # observed (a module-scope `from ... import` would have
                # bound this file's own separate name instead, silently
                # missing the patch -- same pitfall already documented
                # for the re-export hubs elsewhere in this codebase).
                import aryx.cpq.engine as _engine_module  # noqa: PLC0415
                base_model = filled.get(
                    resolve_base_model_vn(filled, workspace_id, catalog_prefix, dt_cache), "",
                )
                product = filled.get("productSelectionProduct_all", "")
                if base_model:
                    candidates = _engine_module._cpq_model_candidates(
                        product, workspace_id, catalog_prefix, dt_cache,
                        base_model=base_model,
                    )
                    legal_results = [
                        _engine_module.dt_resolve_whitelist_values(
                            cm, base_model, target.variable_name, filled,
                            workspace_id, catalog_prefix, dt_cache,
                        )
                        for cm in candidates
                    ]
                    if legal_results and all(r == [] for r in legal_results):
                        hidden_eids.add(target.entity_id)
                        messages.append(
                            f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                        )
                        rule_trace.record_fire(
                            rule_type="hiding", rule_id=rule.rule_name,
                            attr=target.variable_name, outcome="hide",
                            bml_tier="dt_whitelist_substitute",
                            ref_id=getattr(rule, "ref_id", None) or None,
                        )
                        continue
            # Unconfirmed (no workspace_id, no base model yet, no Data
            # Table coverage, or a real legal value exists) -- leave
            # visible, the same safe default as an unresolvable script.
            hidden_eids.discard(target.entity_id)
            continue
        if rule.script is not None:
            if bml_eval is None:
                log_unknown_script_hide(rule, target.variable_name, False)
                _outcomes["unknown"] += 1
                continue
            _rule_t0 = time.monotonic()
            hide = None
            master_tried = False
            if getattr(rule, "master_writers", None) and master_hide_enabled():
                master_tried = True
                # Plan F9: evaluate with the master string COMPUTED from the
                # writer rule + attrSequence; None keeps the ordinary path.
                hide = hide_with_master_string(
                    rule, attrs, by_rule_id, filled, filled_by_rule_id,
                    workspace_id, catalog_prefix, dt_cache)
            if hide is None:
                hide = bml_eval.hide_for_script(rule.script, filled)
            _script_s += time.monotonic() - _rule_t0
            _outcomes["unknown" if hide is None else "hide" if hide else "show"] += 1
            if hide is None:
                log_unknown_script_hide(rule, target.variable_name, True, master_tried)
            if hide is True:
                hidden_eids.add(target.entity_id)
                messages.append(
                    f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                )
                rule_trace.record_fire(
                    rule_type="hiding", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome="hide", bml_tier="script",
                    ref_id=getattr(rule, "ref_id", None) or None,
                )
            elif hide is False:
                hidden_eids.discard(target.entity_id)
                rule_trace.record_fire(
                    rule_type="hiding", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome="show", bml_tier="script",
                    ref_id=getattr(rule, "ref_id", None) or None,
                )
            continue
        if rule.always:
            pass    # plan F10: no condition rows, always true
        elif rule.conditions:
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
                ref_id=getattr(rule, "ref_id", None) or None,
            )
        else:
            hidden_eids.discard(target.entity_id)
            rule_trace.record_fire(
                rule_type="hiding", rule_id=rule.rule_name,
                attr=target.variable_name, outcome="show",
                ref_id=getattr(rule, "ref_id", None) or None,
            )

    hidden_vns = {a.variable_name for a in attrs if a.entity_id in hidden_eids}
    filtered = [a for a in attrs if a.entity_id not in hidden_eids]
    logger.info(
        "cpq_perf: apply_hiding_rules rules=%d script_hide=%d script_show=%d script_unknown=%d script_s=%.3f total_s=%.3f",
        len(rules), _outcomes["hide"], _outcomes["show"], _outcomes["unknown"], _script_s, time.monotonic() - _t0)
    return filtered, messages, hidden_vns
