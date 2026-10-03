"""Attaching share flags plus bidirectional shadow logs to a finished
CPQ turn result, the legacy deterministic CPQ-question auditor, and the
"live quote" routing helper, split out of `api/ask_api.py` (Phase 9/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Logic unchanged from the original inline definitions.
`_cpq_engine`, `logger`, `_run_cpq_turn`, `_attach_share_flags`, and
`_standard_ask_pipeline` are read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path, and `_run_cpq_turn` is not yet split
out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_attach_share_flags as _ask_attach_share_flags_module
from aryx.api import ask_standard_pipeline as _ask_standard_pipeline_module
from aryx.cpq.auto_fill_stages import fill_log
from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision


def _finish_cpq_result(
    result: dict[str, Any] | None,
    req: "Any",
    reader: Any,
    *,
    route_meta: AskRouteDecision | None = None,
) -> dict[str, Any] | None:
    """Attach share flags + bidirectional shadow logs; return result or None."""
    from aryx.api import ask_api as _ask_api_module
    if not result:
        return None
    try:
        _ask_api_module.logger.info(
            "cpq_shadow_intent_actual: tools_called=%s status=%s",
            result.get("tools_called"),
            (result.get("session_data") or {}).get("status"),
        )
        if route_meta is not None:
            _ask_api_module.logger.info(
                "cpq_router: model_id=%s llm_route=%s det_is_cpq=%s agreement=%s "
                "confidence=%s timed_out=%s error=%r tokens=(%d,%d)",
                route_meta.model_id, route_meta.route, route_meta.det_is_cpq,
                route_meta.agreement, route_meta.confidence,
                route_meta.timed_out, route_meta.error,
                route_meta.prompt_tokens, route_meta.completion_tokens,
            )
    except Exception:  # noqa: BLE001
        _ask_api_module.logger.debug("cpq_shadow_intent_actual: logging failed", exc_info=True)
    # G8: turns that ended before step 11 still get their ask.turn.state record
    # (no-op when step 11 already wrote it for this run/turn; never raises).
    fill_log.turn_state_from_session_data(result.get("session_data"))
    _ask_attach_share_flags_module._attach_share_flags(result, req, reader)
    return result


def _deterministic_cpq_gate(req: "Any", reader: Any) -> bool:
    """Legacy auditor: regex/alias only — NO second LLM classification call.

    Demoted from primary router to post-check / escape-hatch path so the
    turn pays at most one gateway LLM call (Prompt 3 acceptance).
    """
    from aryx.api import ask_api as _ask_api_module
    if req.session_data.get("mode") == "cpq":
        return True
    return bool(
        _ask_api_module._cpq_engine.is_cpq_question(req.question, reader, req.workspace_id)
    )


def _route_quote(
    req: "Any", reader: Any, meta: AskRouteDecision | None = None,
) -> dict[str, Any]:
    from aryx.api import ask_api as _ask_api_module
    result = _ask_api_module._run_cpq_turn(req, reader, route_meta=meta)
    finished = _finish_cpq_result(result, req, reader, route_meta=meta)
    if finished:
        return finished
    # No CPQ graph data — fall through to standard Ask rather than empty.
    return _ask_standard_pipeline_module._standard_ask_pipeline(req, reader)
