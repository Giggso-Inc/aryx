"""STEP 6/7/8 routing: awaiting_approval/post_approval review-status
handling for one turn, split out of `_run_cpq_turn_inner` (Phase 10/11-
phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). "approved" is a legacy dead-end value (pre-docs/CPQ_POST_QUOTE_
EDIT_AND_QA_PLAN.md D1) normalized to "post_approval" here so a session
confirmed before this shipped still converges onto the real status. Each
sub-stage (JSON/approval, pending options-query collision, STEP 7 Q&A,
pending change-request collision, the LLM-first gateway, STEP 6 bulk/
removal/activation/clear, change-request collision detection, multi/
single change dispatch, the LLM fallback classifier, and the final
no-value/nudge catch-all) lives in a sibling `ask_step678_*.py` file
purely to keep this orchestrator under the line cap; each returns None
to mean "not this stage, keep going" except the final catch-all, which
always returns. Logic and stage order unchanged from the original inline
block.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_step678_activation_and_clear import _step6_activation_and_clear
from aryx.api.ask_step678_bulk_and_removal import _step6_bulk_and_removal
from aryx.api.ask_step678_change_collision import _resolve_pending_change_collision
from aryx.api.ask_step678_change_collision_detect import _step6_change_collision_detect
from aryx.api.ask_step678_change_dispatch import _step6_change_dispatch
from aryx.api.ask_step678_json_and_approval import _step678_json_or_approval
from aryx.api.ask_step678_llm_fallback import _step6_llm_fallback_classify
from aryx.api.ask_step678_no_value_and_nudge import _step6_no_value_or_nudge
from aryx.api.ask_step678_options_collision import _resolve_pending_options_collision

from aryx.api.ask_handle_llm_first_gateway_turn import _llm_first_gateway_turn
from aryx.api import ask_handle_cpq_qa as _ask_handle_cpq_qa_module


def _handle_review_status_routing(
    req: "Any", session: Any, attrs: list, reader: Any, hints: dict,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    catalog_prefix: str,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was fully handled by the
    awaiting_approval/post_approval review-status routing; None when the
    session isn't in one of those two statuses, in which case the caller
    continues with the rest of the turn unchanged.
    """
    from aryx.api import ask_api as _ask_api_module
    if session.status == "approved":
        session.status = "post_approval"
    if session.status not in ("awaiting_approval", "post_approval"):
        return None

    _cpq_engine = _ask_api_module._cpq_engine

    result = _step678_json_or_approval(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval, hints)
    if result is not None:
        return result

    result = _resolve_pending_options_collision(
        req, session, attrs, reader, catalog_prefix, hiding_rules, rec_rules, con_rules, bml_eval)
    if result is not None:
        return result

    # STEP 7: Q&A during review — answer graph question, then show review again
    if _cpq_engine.detect_qa_question(req.question, strict=False):
        return _ask_handle_cpq_qa_module._handle_cpq_qa(req, session, attrs, reader, resume_review=True)

    result = _resolve_pending_change_collision(req, session, attrs, hiding_rules, rec_rules, con_rules)
    if result is not None:
        return result

    _llm_first_result = _llm_first_gateway_turn(
        req, session, attrs, reader, hints,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
    )
    if _llm_first_result is not None:
        return _llm_first_result
    # action=fallback (or dispatch that couldn't map) → STEP 6+

    result = _step6_bulk_and_removal(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix)
    if result is not None:
        return result

    result = _step6_activation_and_clear(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix)
    if result is not None:
        return result

    result = _step6_change_collision_detect(req, session, attrs)
    if result is not None:
        return result

    result = _step6_change_dispatch(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix)
    if result is not None:
        return result

    result = _step6_llm_fallback_classify(
        req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval)
    if result is not None:
        return result

    return _step6_no_value_or_nudge(req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval)
