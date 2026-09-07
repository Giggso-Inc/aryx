"""Structurally-unresolvable context attrs (Phase 4 step 11 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`find_unresolvable_context_attrs` reports the customerType-class gap:
option-less, script-referenced attrs no rule in the catalog can ever
set. It reuses the same option-less/script-literal scan
`_build_flag_keyword_index` performs, but reports rather than guesses.

`get_cpq_rdb` and `extract_literal_comparisons` are reached off the
engine MODULE object -- `get_cpq_rdb` is patched as
``aryx.cpq.engine.get_cpq_rdb`` by many tests, so a by-value import
would silently break those patches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr, ConstraintRule, RecommendationRule


def find_unresolvable_context_attrs(
    engine: Any,
    attrs: list["ConfigAttr"],
    filled: dict[str, str],
    workspace_id: int,
    catalog_prefix: str,
    rec_rules: list["RecommendationRule"],
    con_rules: list["ConstraintRule"],
) -> list[dict[str, Any]]:
    """Surface every option-less, script-referenced, still-unfilled attr
    that NO rule in this catalog can ever set (the customerType-class
    gap — generalized from a single confirmed instance, docs/
    APX_Next_RootCause_And_Fix_Report).

    Never guesses a value (D2) — this only reports WHICH attrs are
    structurally unresolvable and what literal values scripts elsewhere
    compare them to, so a caller (a standalone payload-construction
    workflow, or a live turn) can decide what to do, instead of the
    gap being invisible the way it was for customerType. Distinct from
    an attr a recommendation rule targets but simply hasn't been run
    yet — call evaluate_recommendation_rules/evaluate_rules_loop
    first; only what remains missing after that pass is a genuine gap
    this method is meant to catch.

    Catalog-agnostic: uses only the same generic option-less/script-
    literal-comparison scan _build_flag_keyword_index already performs,
    and the same rule-target check any catalog's rec/con rules go
    through — no attribute or rule name is hardcoded.

    Returns a list of {variable_name, literal_values_referenced,
    num_referencing_scripts}, one entry per genuinely unresolvable,
    still-missing attr — empty when nothing needs attention.
    """
    by_vn = {a.variable_name: a for a in attrs}
    option_less = {
        vn for vn, a in by_vn.items() if not a.options and not a.hidden
    }
    if not option_less:
        return []

    settable_by_rule: set[int] = set()
    for r in (*rec_rules, *con_rules):
        target_id = getattr(r, "target_attr_id", None)
        if target_id:
            settable_by_rule.add(target_id)

    scripts = _engine_module.get_cpq_rdb().fetch_function_scripts(
        workspace_id, catalog_prefix)
    referenced: dict[str, set[str]] = {}
    referencing_count: dict[str, int] = {}
    for script in scripts.values():
        if not script:
            continue
        seen_this_script: set[str] = set()
        for var, value in _engine_module.extract_literal_comparisons(script):
            if var not in option_less:
                continue
            referenced.setdefault(var, set()).add(value)
            seen_this_script.add(var)
        for var in seen_this_script:
            referencing_count[var] = referencing_count.get(var, 0) + 1

    result: list[dict[str, Any]] = []
    for vn, values in referenced.items():
        if filled.get(vn):
            continue
        attr = by_vn.get(vn)
        eid = attr.entity_id if attr else None
        sid = attr.source_id if attr else None
        if eid in settable_by_rule or (sid is not None and sid in settable_by_rule):
            continue  # a rule CAN fill this — not this method's concern
        result.append({
            "variable_name": vn,
            "literal_values_referenced": sorted(v for v in values if v.strip()),
            "num_referencing_scripts": referencing_count.get(vn, 0),
        })
    result.sort(key=lambda r: -r["num_referencing_scripts"])
    return result
