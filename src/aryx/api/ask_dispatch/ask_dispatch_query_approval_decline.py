"""RESPONSE_MODE_REQUEST, ATTR_QUERY, QA_QUESTION, APPROVAL, and DECLINE
branches of `_dispatch_intent_result`, split out of `api/ask_api.py`
(Phase 7/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline `if`
blocks. `_build_json_preview_response`, `_build_attr_query_response`,
`_handle_cpq_qa`, `_handle_decline`, and `_with_classify_usage` are read
through the ask_api MODULE object (not imported by name) since these
still live in ask_api.py itself (not yet split out) and/or are patched
by ask_api tests via dotted path. `_handle_approval` has already moved
to its own module and is imported directly.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _build_attr_query_response, _with_classify_usage
from aryx.api.ask_json_preview_and_decline import _build_json_preview_response
from aryx.api.ask_handle import ask_handle_cpq_qa as _ask_handle_cpq_qa_module
from aryx.api import ask_json_preview_and_decline as _ask_json_preview_and_decline_module
from aryx.api.ask_handle.ask_handle_approval import _handle_approval
from aryx.api.ask_catalog.ask_target_description import _resolve_target_description
from aryx.cpq.intent_schema.intent_schema import Confidence


def _dispatch_response_mode_request(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 4:
    RESPONSE_MODE_REQUEST has no target at all — same Confidence.HIGH
    gate as APPROVAL/QA_QUESTION (residual-risk mitigation #1). Only
    "json" is wired: the regex path's own detect_response_mode_request
    check for "json" already runs BEFORE this dispatch call site is
    ever reached (STEP 6/7/8 routing, ask_api.py), so this branch only
    fires for phrasing the regex missed. "batch" is a configuring-flow-
    only concept this dispatch call site (scoped to awaiting_approval/
    post_approval only) never reaches, so it's intentionally left
    unwired here.
    """
    if result.confidence != Confidence.HIGH or result.response_mode != "json":
        return None
    return _with_classify_usage(
        _build_json_preview_response(
            req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_attr_query(
    result: Any, req: "Any", session: Any, attrs: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 2 +
    residual-risk mitigation #1: ATTR_QUERY has no deterministic-
    agreement cross-check, so HIGH confidence is required here
    specifically. Read-only, so a wrong dispatch here can't corrupt the
    configuration — only ask about the wrong attribute.
    """
    if result.confidence != Confidence.HIGH or not result.target:
        return None
    attr, _candidates = _resolve_target_description(
        result.target.target_description, attrs)
    if attr is None:
        return None
    return _with_classify_usage(
        _build_attr_query_response(req, session, attrs, con_rules, bml_eval, attr),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_qa_question(
    result: Any, req: "Any", session: Any, attrs: list, reader: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 3:
    QA_QUESTION has no target at all — the category itself is the
    signal. Same Confidence.HIGH gate as ATTR_QUERY. Never dispatches if
    `reader` wasn't actually passed — never guess a graph lookup
    target's data source.
    """
    if result.confidence != Confidence.HIGH or reader is None:
        return None
    return _with_classify_usage(
        _ask_handle_cpq_qa_module._handle_cpq_qa(req, session, attrs, reader, resume_review=True),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_approval(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    hints: dict | None,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md
    `APPROVAL`: dispatched to the SAME _handle_approval the regex path
    now shares. Same Confidence.HIGH gate as ATTR_QUERY/QA_QUESTION —
    the highest-stakes dispatch branch in the file (payload generation/
    submission), so it reuses _handle_approval's own untouched BOM gate
    rather than trusting the classification alone for anything beyond
    "the customer wants to submit."
    """
    if result.confidence != Confidence.HIGH:
        return None
    return _with_classify_usage(
        _handle_approval(
            req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
            hints=hints,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_decline(
    result: Any, req: "Any", session: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """ISSUE-002 fix (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_
    08_17.md): DECLINE is in MUTATING_CATEGORIES, so `result` here
    already passed `_mutating_agrees`'s `detect_decline()` cross-check
    inside `classify_intent` before this function was ever called — the
    SAME classification pass, not a second, unchecked path. Same
    Confidence.HIGH gate as APPROVAL for symmetry/consistency, even
    though the mutating-agreement check already ran upstream.
    """
    if result.confidence != Confidence.HIGH:
        return None
    return _with_classify_usage(
        _ask_json_preview_and_decline_module._handle_decline(req, session),
        classify_prompt_tokens, classify_completion_tokens,
    )
