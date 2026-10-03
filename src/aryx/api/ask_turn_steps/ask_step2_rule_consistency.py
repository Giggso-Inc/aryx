"""Rule-consistency auto-fix logging and array-grid-control detection
for STEP 2, split out of `_run_cpq_turn_inner` (Phase 10/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md —
docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1). A filled attr an
active hiding rule currently matches was never a real customer decision;
constraint/recommendation-type inconsistencies are logged only (not
auto-fixed) since the engine can't be certain what the correct value
should have been. Array-grid controls are flagged, never
auto-populated: the real row->quantity link lives only in BigMachines'
own native-UI array-control widget. Logic unchanged from the original
inline block — none of the values computed here are read again later in
the turn, so nothing is returned; this exists purely for its logging
side effects, same as the original. `_cpq_engine` and `logger` are read
through the ask_api module object (not imported by name) since tests
patch several ask_api names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.raven_log import raven_log, would_log


def _step2_log_rule_consistency_and_array_grid(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> None:
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    _hidden_for_payload = _cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval, filled_multi=session.filled_multi)[2]
    _hidden_for_payload = _hidden_for_payload | _cpq_engine.payload_flow_exclusions(
        req.workspace_id, catalog_prefix, attrs)
    if session.model_leaf_resolved:
        _hidden_for_payload = _hidden_for_payload | _cpq_engine.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules)

    _rule_issues = _cpq_engine.find_rule_inconsistencies(
        session.filled, attrs, hiding_rules, con_rules, rec_rules, bml_eval,
        filled_source=session.filled_source, filled_multi=session.filled_multi,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)
    if _rule_issues:
        logger.info(
            "cpq: rule-consistency check found %d issue(s): %s",
            len(_rule_issues), _rule_issues,
        )
    if would_log("DEBUG"):
        _issue_list = list(_rule_issues or [])
        raven_log("DEBUG", "P4", "ask.preamble.rule_consistency check result", context={
            "selected_option": "issues_found" if _issue_list else "consistent",
            "available_options": ["issues_found", "consistent"],
            "reason_code": "RULE_INCONSISTENCIES" if _issue_list else "RULES_CONSISTENT",
            "issue_count": len(_issue_list),
            "issue_attrs": [i.get("attr") for i in _issue_list if isinstance(i, dict)],
            "issue_rule_types": sorted({str(i.get("rule_type")) for i in _issue_list if isinstance(i, dict)}),
            "hidden_for_payload_count": len(_hidden_for_payload or ()),
            "model_leaf_resolved": bool(getattr(session, "model_leaf_resolved", False)),
            "catalog_prefix": catalog_prefix, "turn": getattr(session, "turn", None)})

    _array_grid_vns = _cpq_engine.array_grid_controls_in_play(attrs)
    if _array_grid_vns:
        logger.info(
            "cpq: array-grid control attr(s) present, not auto-populated "
            "(no rule data links row selection to quantity attrs): %s",
            _array_grid_vns,
        )
        raven_log("DEBUG", "P4", "ask.preamble.array_grid controls flagged, not auto-populated", context={
            "array_grid_vns": list(_array_grid_vns), "array_grid_count": len(_array_grid_vns),
            "reason_code": "ARRAY_GRID_NOT_AUTO_POPULATED", "turn": getattr(session, "turn", None)})
