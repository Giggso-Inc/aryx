"""JSON-preview request and STEP 8 approval detection for the awaiting_
approval/post_approval review status, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Both checked before approval/Q&A/change detection so
"show me the json" is never misread as one of those. Logic unchanged
from the original inline block. Every ask_api name below is read through
the module object (not imported by name) since tests patch several of
them by dotted path (`_handle_approval`, `_build_json_preview_response`,
`_cpq_engine`).
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_handle.ask_handle_approval import _handle_approval
from aryx.api.ask_json_preview_and_decline import _build_json_preview_response
from aryx.raven_log import raven_log

_JA_OPTIONS = ["json_preview", "approval", "continue"]


def _step678_json_or_approval(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, hints: dict,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was a JSON-preview request
    or a STEP 8 explicit approval; None otherwise, in which case the
    caller continues with the rest of the review-status routing.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if _cpq_engine.detect_response_mode_request(req.question) == "json":
        raven_log("INFO", "P4", "ask.review.json_preview requested", context={
            "selected_option": "json_preview", "available_options": _JA_OPTIONS,
            "reason_code": "JSON_MODE_REQUESTED", "status": getattr(session, "status", None),
            "turn": getattr(session, "turn", None)})
        return _build_json_preview_response(
            req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
        )
    if _cpq_engine.detect_approval(req.question):
        raven_log("INFO", "P4", "ask.review.approval detected", context={
            "selected_option": "approval", "available_options": _JA_OPTIONS,
            "reason_code": "EXPLICIT_APPROVAL", "status": getattr(session, "status", None),
            "turn": getattr(session, "turn", None)})
        return _handle_approval(
            req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval, hints=hints,
        )
    return None
