"""Checking whether a country is compatible with a candidate product's
own constraint rules, split out of `_run_cpq_turn_inner` (Phase 10/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Originally a nested closure capturing `reader`/`req` from the
enclosing turn function; rewritten here to take them as explicit
parameters so it can be called from outside `_run_cpq_turn_inner` once
that function is itself split apart. Logic unchanged from the original
inline definition. `_cpq_engine` is read through the ask_api MODULE
object (not imported by name) since at least one test replaces the
whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any



def _country_available_for(
    reader: Any, workspace_id: int, product_name: str, country_value: str,
) -> bool:
    """Best-effort: is country_value compatible with product_name's own
    constraint rules? See CpqEngine.check_country_availability's
    docstring — reuses the same rule-evaluation machinery as every
    other constraint in this engine (declarative AND BML-script-backed
    alike) rather than a hand-rolled lookup. Fails open (True) if the
    new catalog can't be loaded at all — never blocks a switch on an
    inability to check, only on a confirmed real restriction.

    country_value is session.country — DISPLAY text ("United States"),
    not a canonical item_value ("US"), and the new catalog's constraint
    scripts may also read fields DERIVED from the country (region,
    customer type) that a bare one-key dict never contains. So instead
    of seeding check_country_availability with raw text (review finding
    P1: constraints never fired, the check always passed), run the SAME
    cascade a real first turn on the new catalog runs —
    evaluate_rules_loop canonicalizes the country hint to its
    item_value via auto_fill and populates the derived fields via
    recommendation rules — and evaluate availability against that
    resulting filled state. Only runs on a switch turn, never on
    ordinary answers.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    new_attrs, _resolved = _cpq_engine.load_product_config(reader, workspace_id, product_name)
    if not new_attrs:
        return True
    new_prefix = new_attrs[0].catalog_prefix
    country_attr = next(
        (a for a in new_attrs if _cpq_engine._is_country_anchor_var(a.variable_name)), None,
    )
    if country_attr is None:
        return True
    new_hiding = _cpq_engine.load_hiding_rules(workspace_id, new_prefix)
    new_rec_rules, new_con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        workspace_id, new_prefix)
    new_bml_eval = _cpq_engine.build_bml_evaluator(workspace_id, new_prefix)
    # evaluate_rules_loop returns the resulting filled dict (auto_fill
    # copies rather than mutating the one passed in) — capture it.
    _vis, sim_filled, _disp, _copts = _cpq_engine.evaluate_rules_loop(
        new_attrs, {"country": country_value}, {},
        new_hiding, new_rec_rules, new_con_rules,
        bml_eval=new_bml_eval, country=country_value,
        rule_conflict_order=_cpq_engine._load_layout_full_order(workspace_id, new_prefix),
        display_order=_cpq_engine.load_layout_display_order(workspace_id, new_prefix),
        workspace_id=workspace_id, catalog_prefix=new_prefix,
    )
    return _cpq_engine.check_country_availability(
        new_attrs, new_con_rules, sim_filled, new_bml_eval,
        workspace_id=workspace_id, catalog_prefix=new_prefix,
    )
