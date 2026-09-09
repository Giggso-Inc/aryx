"""STEP 2 orchestrator: product resolution, catalog hints, rule-set
loading, and every early-return gate up to (but not including) the
STEP 6/7/8 review-status routing, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Each sub-stage lives in a sibling `ask_step2_*.py`
file purely to keep this orchestrator under the line cap; each returns
None to mean "not this stage, keep going" except the anchor-gates stage,
whose non-None first element means "turn fully handled." Universal
LLM-first cutover (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md §8 Phase
4) is guarded here so status in (awaiting_approval, post_approval) is
never double-classified in the same turn — that status's own call site
(STEP 6/7/8 routing) owns it — and is deferred whenever this turn
STARTED out answering a pending anchor question (country/product/
switch), per `incoming_pending_anchor`'s own live-confirmed regression.
Logic and stage order unchanged from the original inline block.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_model_leaf_resolve import _resolve_model_leaf
from aryx.api.ask_turn_steps.ask_step2_anchor_gates import _step2_resolve_product_and_gates
from aryx.api.ask_turn_steps.ask_step2_catalog_hints import _step2_catalog_hints_and_negation
from aryx.api.ask_turn_steps.ask_step2_pending_change_no_value import _resolve_pending_change_no_value
from aryx.api.ask_turn_steps.ask_step2_rule_consistency import _step2_log_rule_consistency_and_array_grid
from aryx.api.ask_pending_clarify.ask_pending_clarify_turn import _handle_pending_clarify_turn

from aryx.api.ask_handle_llm_first_gateway_turn import _llm_first_gateway_turn


def _step2_resolve_and_load(
    req: "Any", session: Any, reader: Any, hints: dict,
    product_was_anchored: bool, country_llm_call_failed: bool,
    incoming_pending_anchor: str,
) -> "tuple[dict[str, Any] | None, list, str, list, list, list, list, Any, set]":
    """Returns (early_response, attrs, catalog_prefix, hiding_rules,
    rec_rules, con_rules, validation_rules, bml_eval, negated_vns).
    `early_response` is non-None when this turn is fully handled by one
    of the gates in this preamble; the caller must return it immediately
    when present.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    early_response, attrs, switch_trigger_question = _step2_resolve_product_and_gates(
        req, session, reader, hints, product_was_anchored, country_llm_call_failed,
    )
    if early_response is not None:
        return early_response, [], "", [], [], [], [], None, set()

    catalog_prefix, negated_vns = _step2_catalog_hints_and_negation(
        req, session, attrs, hints, switch_trigger_question,
    )

    _model_leaf_response = _resolve_model_leaf(
        req, session, reader, hints, catalog_prefix, switch_trigger_question,
    )
    if _model_leaf_response is not None:
        return _model_leaf_response, [], "", [], [], [], [], None, set()

    _rule_load_t0 = time.monotonic()
    logger.info("cpq_step: load_all_rule_sets start run_id=%s", session.run_id)
    hiding_rules = _cpq_engine.load_hiding_rules(req.workspace_id, catalog_prefix)
    rec_rules, con_rules = _cpq_engine.load_recommendation_and_constraint_rules(
        req.workspace_id, catalog_prefix)
    validation_rules = _cpq_engine.load_validation_rules(req.workspace_id, catalog_prefix)
    bml_eval = _cpq_engine.build_bml_evaluator(req.workspace_id, catalog_prefix)
    logger.info(
        "cpq_step: load_all_rule_sets done run_id=%s elapsed_s=%.3f",
        session.run_id, time.monotonic() - _rule_load_t0,
    )

    _pcnv_response = _resolve_pending_change_no_value(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
    )
    if _pcnv_response is not None:
        return _pcnv_response, [], "", [], [], [], [], None, set()

    _pending_clarify_resp = _handle_pending_clarify_turn(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
    )
    if _pending_clarify_resp is not None:
        return _pending_clarify_resp, [], "", [], [], [], [], None, set()

    _step2_log_rule_consistency_and_array_grid(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
    )

    if (
        _ask_api_module.get_settings().cpq_llm_first_universal_enabled
        and session.status not in ("awaiting_approval", "post_approval")
        and not incoming_pending_anchor
    ):
        _llm_first_universal_result = _llm_first_gateway_turn(
            req, session, attrs, reader, hints,
            hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        )
        if _llm_first_universal_result is not None:
            return _llm_first_universal_result, [], "", [], [], [], [], None, set()

    return None, attrs, catalog_prefix, hiding_rules, rec_rules, con_rules, validation_rules, bml_eval, negated_vns
