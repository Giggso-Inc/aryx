"""Orchestrator for the final response-building tail of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Each response builder
lives in a sibling `ask_step11_*.py` file purely to keep this
orchestrator under the line cap; the dispatch mirrors the original
if/elif/else priority exactly (grid-quantity gap, stale constraint
re-ask, completion, turn cap, then the on-request/FORMAT-A default).
Logic and stage order unchanged from the original inline block — this
is the terminal call in `_run_cpq_turn_inner`, always returning a full
response dict.
"""

from __future__ import annotations

import time
from typing import Any

from aryx.api.ask_turn_steps.ask_grid_batch_quantity import _grid_batch_pending_answer
from aryx.api.ask_turn_steps.ask_step11_completion_responses import (
    _step11_completion_response,
    _step11_grid_gap_response,
    _step11_stale_reask_response,
)
from aryx.api.ask_turn_steps.ask_step11_on_request_response import _step11_on_request_response
from aryx.api.ask_turn_steps.ask_step11_turn_cap_response import _step11_turn_cap_response

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.cpq.auto_fill_stages import fill_log
from aryx.raven_log import raven_log


def _with_model_option_limits(
    session: Any, attrs: list, filled: dict, pending: list, constrained_opts: dict, workspace_id: Any, catalog_prefix: str,
) -> dict:
    """`constrained_opts` plus the model's own values for the pending attributes that separate its base models.

    Base model narrowing (flag): the frequency band / keypad question lists the values the model's base models hold,
    not every option the catalog defines for the attribute. A rule's own constraint is only ever tightened. Any
    failure leaves the options as they were."""
    try:
        from aryx.config import get_settings  # noqa: PLC0415
        if not (pending and get_settings().cpq_base_model_narrowing_enabled):
            return constrained_opts
        from aryx.cpq.base_model_narrowing import discriminator_option_limits  # noqa: PLC0415
        from aryx.cpq.catalog_profile import PRODUCT_LITERAL  # noqa: PLC0415

        product = (session.filled or {}).get(PRODUCT_LITERAL) or session.product_name
        limits = discriminator_option_limits(
            attrs, filled, session.filled_source, product, workspace_id, catalog_prefix)
        pending_ids = {getattr(a, "entity_id", None) for a in pending}
        limits = {eid: vals for eid, vals in limits.items() if eid in pending_ids}
        if not limits:
            return constrained_opts
        merged = dict(constrained_opts)
        for eid, vals in limits.items():
            existing = merged.get(eid)
            merged[eid] = vals if existing is None else [v for v in vals if v in existing] or existing
        _log_model_limits(session, pending, limits, merged)
        return merged
    except Exception as exc:  # noqa: BLE001 -- never affects the question
        raven_log("DEBUG", "P4", "ask.options.model_limits failed", context={
            "run_id": session.run_id, "error_class": type(exc).__name__})
        return constrained_opts


def _log_model_limits(session: Any, pending: list, limits: dict, merged: dict) -> None:
    """One DEBUG record per limited question: how many options are offered of how many the catalog has."""
    for attr in pending:
        eid = getattr(attr, "entity_id", None)
        if eid in limits:
            raven_log("DEBUG", "P4", "ask.options.model_limits options limited to the model's own values", context={
                "selected_option": "limited", "available_options": ["limited", "full_list"],
                "reason_code": "MODEL_DISCRIMINATOR_VALUES", "attribute": getattr(attr, "variable_name", None),
                "offered_count": len(merged.get(eid) or []), "catalog_option_count": len(getattr(attr, "options", None) or []),
                "run_id": session.run_id, "turn": getattr(session, "turn", None)})


def _step11_build_turn_response(
    req: "Any", session: Any, attrs: list, hints: dict, visible_attrs: list,
    filled: dict, display_filled: dict, pending: list, constrained_opts: dict,
    rule_ids: set, dropped_note: str, hiding_rules: list, rec_rules: list,
    con_rules: list, validation_rules: list, bml_eval: Any, catalog_prefix: str,
    mode_request: str | None,
) -> dict[str, Any]:
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger
    _step_format_t0 = time.monotonic()
    logger.info(
        "cpq_step: step6_4_response_formatting start run_id=%s pending=%d",
        session.run_id, len(pending),
    )

    constrained_opts = _with_model_option_limits(
        session, visible_attrs, filled, pending, constrained_opts, req.workspace_id, catalog_prefix)
    _branch = "on_request_next_question"
    if not pending:
        _branch = "grid_gap"
        answer = _step11_grid_gap_response(session, visible_attrs, dropped_note)
        if answer is None:
            _branch = "stale_reask"
            answer = _step11_stale_reask_response(
                req, session, attrs, con_rules, bml_eval, catalog_prefix, dropped_note,
            )
        if answer is None:
            _branch = "completion"
            answer = _step11_completion_response(
                req, session, attrs, display_filled, rule_ids, dropped_note,
            )
    elif session.turn >= _ask_api_module._cpq_engine.MAX_TURNS:
        # 2026-09-01 (ported from dev-rv-msi #305): the turn cap must not
        # force one-mount-at-a-time either, or a customer who's already
        # past MAX_TURNS elsewhere in a large configuration gets stuck
        # answering one grid's own quantities one by one with no way out.
        # An explicit mode_request ("json"/"batch") still takes priority --
        # skip grid-batching entirely and fall through to the pre-existing
        # turn-cap response unchanged.
        _grid_batch = (
            _grid_batch_pending_answer(
                pending, visible_attrs, filled, display_filled, hiding_rules,
                rec_rules, constrained_opts, validation_rules, dropped_note,
            )
            if mode_request is None else None
        )
        if _grid_batch is not None:
            _branch = "turn_cap_grid_batch"
            session.status = "configuring"
            answer = _grid_batch
        else:
            _branch = "turn_cap"
            answer = _step11_turn_cap_response(
                req, session, visible_attrs, pending, constrained_opts, validation_rules,
            )
    else:
        answer = _step11_on_request_response(
            req, session, attrs, visible_attrs, filled, display_filled, pending,
            constrained_opts, rule_ids, hiding_rules, rec_rules, con_rules,
            validation_rules, bml_eval, catalog_prefix, mode_request, dropped_note,
        )

    logger.info(
        "cpq_step: step6_4_response_formatting done run_id=%s elapsed_s=%.3f",
        session.run_id, time.monotonic() - _step_format_t0,
    )
    raven_log("INFO", "P4", "ask.answer.branch answer branch chosen", context={
        "selected_option": _branch,
        "available_options": ["grid_gap", "stale_reask", "completion", "turn_cap_grid_batch",
                              "turn_cap", "on_request_next_question"],
        "reason_code": "NO_PENDING" if not pending else "PENDING_OPEN",
        "policy_version": "step11_v1", "open_question_count": len(pending),
        "open_fields": [getattr(p, "variable_name", str(p)) for p in pending][:25],
        "turn": getattr(session, "turn", None), "max_turns": _ask_api_module._cpq_engine.MAX_TURNS,
        "mode_request": mode_request, "status": session.status,
        "answer_len": len(answer or ""), "run_id": session.run_id,
        "duration_ms": int((time.monotonic() - _step_format_t0) * 1000),
    })
    try:
        fill_log.build_turn_state_record(session, attrs)  # G8 end-of-turn state record
    except Exception:  # noqa: BLE001 - logging must never break the turn
        raven_log("DEBUG", "P4", "ask.turn.state record failed", context={"run_id": session.run_id})
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer,
        "terms": list(hints.values()),
        "tools_called": [f"cpq_config_load(product={session.product_name})"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None,
        "session_data": session.to_dict(),
        "cpq_payload": None,  # payload only generated on STEP 8 approval
        "preview": mode_request == "json",
    }
