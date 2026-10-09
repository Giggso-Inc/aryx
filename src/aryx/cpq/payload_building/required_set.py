"""The derived required-attribute set (plan F6, with F4 and F13).

One function decides which attributes the real screen marks required, so that
``config_data``, beautify's "Mandatory User Input" section and the chat summary
agree. Nothing here names a product, model, attribute or value: it reads the
ingested attrSequence table, the loaded rules and the quote state.

An attribute is required when ALL of these hold:

1. it is a candidate: its attrSequence row is flagged ``R`` for the resolved
   base model (or for EVERY base model of the model while the base model is not
   resolved yet), OR a blank-disallow constraint action fires for it, OR a
   message-only validation rule fires for it (F4);
2. it is visible: not catalog-hidden, not hidden by a rule, and present in the
   layout's visible order when a layout is loaded;
3. its value, if any, was not put there by the catalog itself (a catalog
   default, a data-table default or a rule): such an attribute is never red;
4. the data tables do not confirm that no value is legal for it.

A rule whose condition cannot be evaluated yet is "unknown" and never makes an
attribute required (F13).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from aryx.config import get_settings
from aryx.cpq import engine as _engine_module
from aryx.cpq.bml.bml_declarative import evaluate_declarative_conditions
from aryx.cpq.catalog_profile import PRODUCT_LITERAL, resolve_base_model_vn
from aryx.cpq.constraint_rules.constraint_rules_mode import guard_open
from aryx.cpq.data_table.data_table_getconstraintvals import get_constraint_vals
from aryx.cpq.data_table.data_table_loader import _load_all_tables
from aryx.cpq.data_table_bridge.series_narrowing import narrow_models_by_series
from aryx.cpq.hiding_rules.attr_index import _attr_index, _filled_by_rule_id

logger = logging.getLogger(__name__)

# Source tags the engine writes when the CATALOG filled a value (a catalog
# default, a Defaultinattr/data-table value, a recommendation rule). The engine's
# own guesses (blind picks, first-available) are deliberately not in this set.
CATALOG_FILL_SOURCES = frozenset({"default", "data_table", "rule"})


def r_flagged_names(
    cpq_models: list[str], base_model: str, workspace_id: int, catalog_prefix: str,
    cache: dict | None,
) -> set[str]:
    """AttrNames flagged ``R`` in attrSequence: for `base_model` when given,
    otherwise those flagged ``R`` on every base model of a model."""
    _, sequence_rows, *_ = _load_all_tables(workspace_id, catalog_prefix, cache)
    out: set[str] = set()
    for cpq_model in cpq_models:
        by_base: dict[str, set[str]] = defaultdict(set)
        bases: set[str] = set()
        for row in sequence_rows:
            if row.get("CPQModel") != cpq_model:
                continue
            base = str(row.get("BaseModel") or "")
            bases.add(base)
            if row.get("optionOrReqFlag") == "R":
                by_base[base].add(str(row.get("AttrName") or ""))
        generic = by_base.get("ALL", set())
        if base_model:
            out |= by_base.get(base_model, set()) | generic
            continue
        real = [b for b in bases if b and b.upper() != "ALL"]
        if real:
            out |= set.intersection(*(by_base.get(b, set()) | generic for b in real))
    out.discard("")
    return out


def _condition_states(conditions: Any, by_rule_id: dict[int, str], by_id: dict[int, Any], limit: int = 6) -> list[list[str]]:
    """Diagnostic: for each condition of a rule, [attribute, operator, value, state] where state is `unmapped` (the attribute is
    not in the list the check was given, so its value can never be read), `true`, `false` or `unknown`. Never affects a result."""
    out: list[list[str]] = []
    for attr_id, value, operator in list(conditions or [])[:limit]:
        attr = by_id.get(attr_id)
        name = attr.variable_name if attr is not None else f"id:{attr_id}"
        if attr_id not in by_rule_id:
            state = "unmapped"
        else:
            matched, _blocked = evaluate_declarative_conditions([(attr_id, value, operator)], by_rule_id)
            state = "true" if matched is True else "false" if matched is False else "unknown"
        out.append([name[:48], str(operator), str(value)[:24], state])
    return out


def _fires(conditions: Any, filled_by_rule_id: dict[int, str]) -> bool:
    """True only when a declarative condition is decided True (never unknown)."""
    if not conditions:
        return False
    matched, _blocked = evaluate_declarative_conditions(conditions, filled_by_rule_id)
    return matched is True


def script_filled_quantity_vns(engine: Any, attrs: list[Any], rec_rules: list[Any]) -> set[str]:
    """Per-option quantity attributes (array-grid members) that an active
    script-backed recommendation rule fills. Real CPQ prefills them, so they are
    never red even though the engine's grid flow asks for them (plan F15)."""
    by_id = _attr_index(attrs)
    filled_by_rule = {
        by_id[r.target_attr_id].variable_name
        for r in rec_rules if r.script is not None and r.target_attr_id in by_id
    }
    quantity: set[str] = set()
    for per_option in engine.resolve_array_grid_links(attrs).values():
        quantity.update(per_option.values())
    return quantity & filled_by_rule


def _assumed_master_string_attrs(attrs: list[Any], filled: dict[str, str], filled_multi: dict[str, list[str]] | None) -> list[Any]:
    """Flag `cpq_required_set_master_string_present_enabled`: the hidden, option-less 'MasterString' attributes the quote
    does not fill (see the setting's description). Empty with the flag off."""
    if getattr(get_settings(), "cpq_required_set_master_string_present_enabled", False) is not True:
        return []
    return [a for a in attrs
            if getattr(a, "hidden", False) and "masterstring" in a.variable_name.lower() and not getattr(a, "options", None)
            and a.variable_name not in filled and not (filled_multi or {}).get(a.variable_name)]


def _assumed_master_strings(attrs: list[Any], filled: dict[str, str], filled_multi: dict[str, list[str]] | None) -> dict[int, str]:
    """Entity/source ids of the assumed attributes, mapped to a non-blank stand-in value."""
    out: dict[int, str] = {}
    for a in _assumed_master_string_attrs(attrs, filled, filled_multi):
        out[a.entity_id] = "ASSUMED_PRESENT"
        if a.source_id is not None:
            out[a.source_id] = "ASSUMED_PRESENT"
    return out


def rule_required_vns(
    engine: Any, attrs: list[Any], filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None, workspace_id: int, catalog_prefix: str,
    rules: tuple[list[Any], list[Any]] | None = None, stats: dict | None = None,
) -> set[str]:
    """Targets of a firing blank-disallow constraint action or a firing
    message-only validation rule. `stats`, when given, receives diagnostic counts (never affects the result)."""
    by_id = _attr_index(attrs)
    by_rule_id = {**_assumed_master_strings(attrs, filled, filled_multi), **_filled_by_rule_id(attrs, filled, filled_multi)}
    settings = get_settings()
    assume_open = bool(getattr(settings, "cpq_required_set_guards_assumed_open", False)
                       or getattr(settings, "cpq_required_set_rule_guards_assumed_open", False) is True)
    out: set[str] = set()
    _rec, con_rules = rules or engine.load_recommendation_and_constraint_rules(workspace_id, catalog_prefix)
    counts = {"blank_disallow_loaded": 0, "blank_disallow_condition_fired": 0, "blank_disallow_guard_closed": 0,
              "blank_disallow_target_missing": 0, "validation_loaded": 0, "validation_fired": 0}
    unfired: list[dict] = []
    for rule in con_rules:
        if str(getattr(rule, "mode", "")).upper() != "DISALLOW" or not getattr(rule, "blank", False):
            continue
        counts["blank_disallow_loaded"] += 1
        if rule.condition_script is not None or not _fires(rule.conditions, by_rule_id):
            if stats is not None and len(unfired) < 20:       # diagnostic: why this blank-disallow rule did not fire
                target = by_id.get(rule.target_attr_id)
                unfired.append({
                    "rule": str(getattr(rule, "rule_name", ""))[:55], "target": target.variable_name if target else f"id:{rule.target_attr_id}",
                    "script_condition": rule.condition_script is not None,
                    "conds": _condition_states(rule.conditions, by_rule_id, by_id)})
            continue
        counts["blank_disallow_condition_fired"] += 1
        guard = getattr(rule, "guard_attr", "")
        if guard and not guard_open(rule, filled, assume_open):
            counts["blank_disallow_guard_closed"] += 1
            continue
        target = by_id.get(rule.target_attr_id)
        if target is not None:
            out.add(target.variable_name)
        else:
            counts["blank_disallow_target_missing"] += 1
    for rule in engine.load_validation_rules(workspace_id, catalog_prefix):
        counts["validation_loaded"] += 1
        if rule.condition_script is None and _fires(rule.conditions, by_rule_id):
            counts["validation_fired"] += 1
            target = by_id.get(rule.target_attr_id)
            if target is not None:
                out.add(target.variable_name)
    if stats is not None:
        stats.update(counts)
        stats["unfired_blank_disallow"] = unfired
        stats["assumed_master_strings"] = len(_assumed_master_string_attrs(attrs, filled, filled_multi))
    return out


def no_legal_value(
    engine: Any, vn: str, filled: dict[str, str], models: list[str], base_model: str,
    workspace_id: int, catalog_prefix: str, cache: dict | None,
) -> bool:
    """True when the data tables confirm that no value is legal for `vn` right now.

    With the constraint-values port on (flag `cpq_getconstraintvals_port_enabled`)
    and a resolved base model, the answer is the port's: every model that has
    rows for the attribute returns an empty list (an earlier attribute that is
    not answered yet also empties it, which is why such a field is not red
    until its predecessors are answered). Otherwise the engine's whitelist
    resolver decides. Unknown (no rows) is never "no legal value"."""
    if base_model and get_settings().cpq_getconstraintvals_port_enabled:
        results = [
            get_constraint_vals(cm, base_model, vn, filled, workspace_id, catalog_prefix, cache)
            for cm in models
        ]
        known = [r for r in results if r is not None]
        if known:
            return all(not r["values"] for r in known)
    return engine._resolve_narrowed_legal_values(vn, filled, workspace_id, catalog_prefix, cache) == []


def _visible(attr: Any, hidden_vns: set[str], display_order: dict[str, int] | None) -> bool:
    if attr.hidden or attr.hide_in_trans or attr.variable_name in hidden_vns:
        return False
    return display_order is None or attr.variable_name in display_order


def _invisible_reason(attr: Any, hidden_vns: set[str], display_order: dict[str, int] | None) -> str:
    """Diagnostic label for why `_visible` is False (same order of checks)."""
    if attr.hidden:
        return "catalog_hidden"
    if attr.hide_in_trans:
        return "hide_in_trans"
    if attr.variable_name in hidden_vns:
        return "hidden_by_rule"
    return "not_in_layout"


def _log_required_set_diagnostic(*, rule_only: bool, stats: dict, found: set[str], dropped: dict[str, str],
                                 kept: set[str], models: list[str], base_model: str, attr_count: int) -> None:
    """ask.required_set.diagnostic (DEBUG): what the rules found and why each candidate was kept or dropped. Answers "why is
    this attribute (not) in the asked set" from the log alone."""
    try:
        from aryx.raven_log import raven_log, would_log  # noqa: PLC0415 -- diagnostic only

        if not would_log("DEBUG"):
            return
        raven_log("DEBUG", "P4", "ask.required_set.diagnostic why each candidate was kept or dropped", context={
            "selected_option": "computed", "available_options": ["computed"], "reason_code": "REQUIRED_SET_DIAGNOSTIC",
            "rule_required_only": rule_only, "attr_count": attr_count, "models": models[:4], "base_known": bool(base_model),
            "rule_found": sorted(found)[:25], "kept": sorted(kept)[:25],
            "dropped": dict(sorted(dropped.items())[:30]), **stats})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change the required set
        return


def derive_required_vns(
    engine: Any, attrs: list[Any] | None, filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None, filled_source: dict[str, str] | None,
    hidden_vns: set[str] | None, display_order: dict[str, int] | None,
    workspace_id: int | None, catalog_prefix: str = "", product_hint: str = "",
    cache: dict | None = None, rule_required_only: bool = False,
) -> frozenset[str]:
    """The derived required variable names (see the module docstring).

    `rule_required_only`: candidates come only from the rules (a firing blank-disallow constraint action or message-only
    validation rule), not from attrSequence `R`. Used when the set decides what Ask must ASK: an `R` attribute the
    engine cannot see a default for is very often filled by a script the real CPQ runs (ws 1267, APX 900: Do You Require
    Radio FCC Trigger? is `R` on every base model, was filled YES by the blind pick, and is not red on the real screen)."""
    if not attrs or workspace_id is None:
        return frozenset()
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    product = filled.get(PRODUCT_LITERAL, "") or product_hint
    candidates: set[str] = set()
    models: list[str] = []
    if product:
        models = list(_engine_module._cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model or ""))
        if get_settings().cpq_series_model_narrowing_enabled:
            models = narrow_models_by_series(models, filled, workspace_id, catalog_prefix, cache)    # plan F8
        if not rule_required_only:
            candidates |= r_flagged_names(models, base_model, workspace_id, catalog_prefix, cache)
    rules = engine.load_recommendation_and_constraint_rules(workspace_id, catalog_prefix)
    rule_stats: dict = {}
    rule_found = rule_required_vns(engine, attrs, filled, filled_multi, workspace_id, catalog_prefix, rules, rule_stats)
    candidates |= rule_found
    quantity_filled = script_filled_quantity_vns(engine, attrs, rules[0])
    candidates -= quantity_filled
    by_vn = {a.variable_name: a for a in attrs}
    sources = filled_source or {}
    hidden = hidden_vns or set()
    out: set[str] = set()
    dropped: dict[str, str] = {vn: "script_filled_quantity" for vn in quantity_filled & rule_found}
    for vn in candidates:
        attr = by_vn.get(vn)
        if attr is None:
            dropped[vn] = "not_in_attribute_list"
            continue
        if not _visible(attr, hidden, display_order):
            dropped[vn] = _invisible_reason(attr, hidden, display_order)
            continue
        has_value = bool(filled.get(vn) or (filled_multi or {}).get(vn))
        if has_value and sources.get(vn) in CATALOG_FILL_SOURCES:
            dropped[vn] = "catalog_filled"
            continue
        if no_legal_value(engine, vn, filled, models, base_model, workspace_id, catalog_prefix, cache):
            dropped[vn] = "no_legal_value"    # the data tables confirm no value is legal right now
            continue
        out.add(vn)
    _log_required_set_diagnostic(rule_only=rule_required_only, stats=rule_stats, found=rule_found, dropped=dropped,
                                 kept=out, models=models, base_model=base_model, attr_count=len(attrs))
    return frozenset(out)


def log_shadow_difference(label: str, derived: frozenset[str], current: frozenset[str] | set[str]) -> None:
    """Shadow mode (flag `cpq_required_set_shadow_enabled`): log how the derived
    set differs from the current classification. Never changes any output."""
    only_derived = sorted(derived - set(current))
    only_current = sorted(set(current) - derived)
    logger.info(
        "cpq: required_set shadow %s derived=%d current=%d only_derived=%s only_current=%s",
        label, len(derived), len(current), only_derived[:40], only_current[:40],
    )
