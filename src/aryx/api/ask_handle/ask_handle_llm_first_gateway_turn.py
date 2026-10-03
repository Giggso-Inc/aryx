"""LLM-first classify-and-dispatch for one turn, split out of `api/
ask_api.py` (Phase 7/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definition; the defer-check, compound-split-on-clarify, and resolve-or-
reask stages live in sibling `ask_gateway_*.py` files purely to keep
this file under the line cap. `_cpq_engine`, `logger`, and several
not-yet-split ask_api.py names are read through the ask_api MODULE
object (not imported by name) since ask_api tests patch several of its
own module-level names by dotted path, and some of these names still
live in ask_api.py itself.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_dispatch.ask_dispatch_intent_result import _dispatch_intent_result
from aryx.api.ask_gateway.ask_gateway_compound_split import _try_compound_split_on_clarify
from aryx.api.ask_gateway.ask_gateway_defer_check import _should_defer_gateway_to_pending_answer
from aryx.api.ask_gateway.ask_gateway_resolve_or_reask import _resolve_or_reask_ambiguous
from aryx.api.ask_gateway.ask_gateway_to_intent_result import _gateway_to_intent_result
from aryx.api.ask_pending_clarify.ask_pending_clarify_apply import _clear_pending_clarify
from aryx.cpq.intent_gateway.intent_gateway import classify_intent as gateway_classify_intent
from aryx.cpq.intent_schema.intent_schema import IntentCategory
from aryx.cpq.session_guard.session_guard import clear_clarify
from aryx.raven_log import raven_log


def _llm_first_gateway_turn(
    req: "Any", session: Any, attrs: list, reader: Any, hints: dict | None,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    catalog_prefix: str,
) -> "dict[str, Any] | None":
    """LLM-first classify-and-dispatch for one turn — the single call site
    both the post-approval review flow AND (behind
    `cpq_llm_first_universal_enabled`) the configuring-stage flow share
    (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md §8 Phase 4).

    Factored out of what used to be inline code nested inside the
    `awaiting_approval`/`post_approval` status branch only — that
    scoping meant this dispatcher, despite already resolving 12 of 16
    `IntentCategory` values, never ran during the actual configuring
    conversation (most real traffic). Extracting it here, unchanged in
    behavior, is what lets a second call site reuse it instead of
    duplicating ~200 lines, satisfying the plan doc's own "one
    classification, one handler call, no double-dispatch" convergence
    discipline (§5/§6 mitigation #5) for both call sites at once.

    Returns a full response dict when the turn was fully handled, or
    None when the LLM/deterministic layers found nothing dispatchable —
    callers MUST treat None as "fall through to the unchanged
    deterministic path," exactly like `_dispatch_intent_result`'s own
    contract.
    """
    from aryx.api import ask_api as _ask_api_module
    _defer_gateway_to_pending_answer = _should_defer_gateway_to_pending_answer(
        req, session, attrs,
    )
    # N4: skip when top-level classify_ask_route already ran this turn
    # (one classification LLM call per turn). Live sessions never mark
    # top-level, so they still get this gateway. Guided mode stays
    # deterministic-only.
    if not (
        _ask_api_module.get_settings().cpq_llm_first_enabled
        and not session.guided_mode
        and not _ask_api_module.top_level_route_used()
        and not _defer_gateway_to_pending_answer
    ):
        raven_log("DEBUG", "P4", "ask.intent.gateway_turn gateway not run", context={
            "selected_option": "skip", "available_options": ["run", "skip"],
            "reason_code": (
                "LLM_FIRST_DISABLED" if not _ask_api_module.get_settings().cpq_llm_first_enabled
                else "GUIDED_MODE" if session.guided_mode
                else "TOP_LEVEL_ROUTE_USED" if _ask_api_module.top_level_route_used()
                else "DEFER_TO_PENDING_ANSWER"),
            "guided_mode": bool(session.guided_mode), "turn": getattr(session, "turn", None),
            "ran_and_did_nothing": False})
        return None

    _gw = gateway_classify_intent(
        req.question, attrs, session, _ask_api_module._cpq_engine, req.workspace_id,
        hiding_rules=hiding_rules, rec_rules=rec_rules, con_rules=con_rules,
        bml_eval=bml_eval, catalog_prefix=catalog_prefix,
    )
    _ask_api_module.logger.info(
        "cpq_intent_gateway_turn: action=%s reason=%r category=%s "
        "vn=%r value_ref=%r cache_hit=%s tokens=(%d,%d) model=%s",
        _gw.action, _gw.reason,
        _gw.result.intent_category.value if _gw.result else None,
        _gw.result.variable_name if _gw.result else None,
        _gw.result.value_ref if _gw.result else None,
        _gw.cache_hit, _gw.prompt_tokens, _gw.completion_tokens,
        _gw.model_id,
    )
    if _gw.action == "clarify" and _gw.result:
        _split_response = _try_compound_split_on_clarify(
            req, session, attrs, hiding_rules, rec_rules, con_rules, reader,
        )
        if _split_response is not None:
            return _split_response
        return _resolve_or_reask_ambiguous(
            req, session, attrs, _gw, hiding_rules, rec_rules, con_rules, bml_eval,
            _gw.result.clarifying_question, "cpq_intent_gateway_clarify()",
        )
    if _gw.action == "dispatch" and _gw.result:
        clear_clarify(session, _gw.result.variable_name)
        # Successful non-clarify path — drop any stale clarify memory.
        _clear_pending_clarify(session)
        _mapped = _gateway_to_intent_result(_gw.result, attrs, _gw.value_display)
        if _mapped is not None:
            # AMBIGUOUS via dispatch path must also set pending memory.
            if _mapped.category == IntentCategory.AMBIGUOUS:
                return _resolve_or_reask_ambiguous(
                    req, session, attrs, _gw, hiding_rules, rec_rules, con_rules, bml_eval,
                    _mapped.clarifying_question, "cpq_llm_first_ambiguous()",
                )
            _dispatched = _dispatch_intent_result(
                req, session, attrs, _mapped,
                hiding_rules, rec_rules, con_rules, bml_eval,
                _gw.prompt_tokens, _gw.completion_tokens,
                reader=reader, hints=hints,
            )
            if _dispatched is not None:
                return _dispatched
            _ask_api_module.logger.info(
                "cpq_intent_gateway_turn: dispatch mapped but handler "
                "returned None — falling through to deterministic path",
            )
    # action=fallback (or dispatch that couldn't map) → caller's own
    # deterministic path.
    raven_log("DEBUG", "P4", "ask.intent.gateway_turn gateway ran and did nothing", context={
        "selected_option": "fall_through", "reason_code": _gw.reason or f"ACTION_{_gw.action.upper()}",
        "gateway_action": _gw.action, "turn": getattr(session, "turn", None), "ran_and_did_nothing": True,
        "category": _gw.result.intent_category.value if _gw.result else None})
    return None
