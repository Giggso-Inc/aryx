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

from aryx.api.ask_turn_steps.ask_step11_completion_responses import (
    _step11_completion_response,
    _step11_grid_gap_response,
    _step11_stale_reask_response,
)
from aryx.api.ask_turn_steps.ask_step11_on_request_response import _step11_on_request_response
from aryx.api.ask_turn_steps.ask_step11_turn_cap_response import _step11_turn_cap_response

from aryx.api import ask_core_helpers as _ask_core_helpers_module


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

    if not pending:
        answer = _step11_grid_gap_response(session, visible_attrs, dropped_note)
        if answer is None:
            answer = _step11_stale_reask_response(
                req, session, attrs, con_rules, bml_eval, catalog_prefix, dropped_note,
            )
        if answer is None:
            answer = _step11_completion_response(
                req, session, attrs, display_filled, rule_ids, dropped_note,
            )
    elif session.turn >= _ask_api_module._cpq_engine.MAX_TURNS:
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
