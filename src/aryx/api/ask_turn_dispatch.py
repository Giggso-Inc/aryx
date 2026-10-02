"""The 8-step CPQ turn dispatch chain, split out of `_run_cpq_turn_inner`
(docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md ask_api.py external-import-
site rewrite — the line-count-reduction step). Every extracted step/
preamble module this dispatches through in turn order; logic and stage
order unchanged from the original inline body. `logger` is read through
the ask_api module object (not imported by name) since ask_api.py is its
sole definition site and tests patch several ask_api names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_preamble.ask_preamble_run import _preamble_run
from aryx.api.ask_run_ask import note_step
from aryx.raven_log import raven_log
from aryx.api.ask_turn_steps.ask_step1_product_anchor import _step1_resolve_product_anchor
from aryx.api.ask_turn_steps.ask_step2_resolve_and_load import _step2_resolve_and_load
from aryx.api.ask_turn_steps.ask_step678_review_status import _handle_review_status_routing
from aryx.api.ask_turn_steps.ask_step8_pre_step5_gates import _step8_run_pre_step5_gates
from aryx.api.ask_turn_steps.ask_step9_lock_pending_answer import _step9_lock_pending_answer
from aryx.api.ask_turn_steps.ask_step10_rule_eval_loop import _step10_run_rule_eval_loop
from aryx.api.ask_turn_steps.ask_step11_build_response import _step11_build_turn_response
from aryx.api.ask_turn_switch.ask_turn_product_switch_anchor import _handle_product_switch_pending_anchor


def _gate(name: str, early: Any, session: Any = None) -> None:
    """Record which turn gate ran and whether it handled the turn (R-deep trail)."""
    note_step(name)
    raven_log("DEBUG", "P4", "ask.turn.gate gate evaluated", context={
        "gate": name, "handled_turn": early is not None,
        "result": "handled" if early is not None else "continue",
        "turn": getattr(session, "turn", None), "status": getattr(session, "status", None),
        "product": getattr(session, "product_name", "") or "",
    })


def _dispatch_cpq_turn_steps(
    req: "Any", reader: Any, route_meta: "Any | None" = None,
) -> dict[str, Any]:
    """Body of ``_run_cpq_turn_inner`` — see ``_run_cpq_turn`` for the step contract."""
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger

    (
        _preamble_early_response, session, hints, _country_llm_call_failed,
        _incoming_pending_anchor,
    ) = _preamble_run(req, reader, route_meta)
    _gate("preamble", _preamble_early_response, session)
    if _preamble_early_response is not None:
        return _preamble_early_response

    logger.info("cpq_step: mid_session_product_switch_gate enter run_id=%s", session.run_id)
    _switch_anchor_response = _handle_product_switch_pending_anchor(
        req, session, reader, hints,
    )
    _gate("mid_session_product_switch_gate", _switch_anchor_response, session)
    if _switch_anchor_response is not None:
        return _switch_anchor_response
    # Whether the product was anchored BEFORE this turn — switch detection
    # must only run for messages sent to an already-anchored session,
    # never on the very message that anchored it.
    product_was_anchored = bool(session.product_name)
    _step1_response = _step1_resolve_product_anchor(req, session, reader, hints)
    _gate("step1_anchor", _step1_response, session)
    if _step1_response is not None:
        return _step1_response

    (
        _step2_early_response, attrs, catalog_prefix, hiding_rules, rec_rules,
        con_rules, validation_rules, bml_eval, negated_vns,
    ) = _step2_resolve_and_load(
        req, session, reader, hints, product_was_anchored, _country_llm_call_failed,
        _incoming_pending_anchor,
    )
    _gate("step2_resolve_and_load", _step2_early_response, session)
    if _step2_early_response is not None:
        return _step2_early_response

    logger.info(
        "cpq_step: step6_7_8_routing_gate enter run_id=%s status=%s",
        session.run_id, session.status,
    )
    review_status_result = _handle_review_status_routing(
        req, session, attrs, reader, hints,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
    )
    _gate("review_status_routing", review_status_result, session)
    if review_status_result is not None:
        return review_status_result

    _step8_early_response, mode_request = _step8_run_pre_step5_gates(
        req, session, attrs, reader, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix,
    )
    _gate("step8_pre_step5_gates", _step8_early_response, session)
    if _step8_early_response is not None:
        return _step8_early_response

    logger.info("cpq_step: step5_lock_answer_gate enter run_id=%s", session.run_id)
    _step9_early_response, pending_var = _step9_lock_pending_answer(
        req, session, attrs, hints, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix, mode_request,
    )
    _gate("step9_lock_pending_answer", _step9_early_response, session)
    if _step9_early_response is not None:
        return _step9_early_response

    logger.info("cpq_step: step5b_blocked_removal_gate enter run_id=%s", session.run_id)
    (
        _step10_early_response, visible_attrs, filled, display_filled, pending,
        constrained_opts, rule_ids, dropped_note,
    ) = _step10_run_rule_eval_loop(
        req, session, attrs, hints, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix, negated_vns, mode_request,
        pending_var,
    )
    _gate("step10_rule_eval_loop", _step10_early_response, session)
    if _step10_early_response is not None:
        return _step10_early_response

    note_step("step11_build_response")
    return _step11_build_turn_response(
        req, session, attrs, hints, visible_attrs, filled, display_filled, pending,
        constrained_opts, rule_ids, dropped_note, hiding_rules, rec_rules, con_rules,
        validation_rules, bml_eval, catalog_prefix, mode_request,
    )
