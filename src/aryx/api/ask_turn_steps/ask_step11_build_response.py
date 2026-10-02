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
