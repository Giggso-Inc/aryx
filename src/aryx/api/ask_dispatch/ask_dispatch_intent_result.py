"""Phase 2 (PARTIAL) LLM-first dispatch to the existing regex-path
handlers, split out of `api/ask_api.py` (Phase 7/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Each
category is its own function in a sibling `ask_dispatch_*.py` file
purely to keep this file under the line cap; this file only sequences
the category checks the original inline `if`/`elif` chain performed.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_dispatch.ask_dispatch_ambiguous_and_scope import (
    _dispatch_ambiguous,
    _dispatch_out_of_scope,
)
from aryx.api.ask_dispatch.ask_dispatch_attr_activation import _dispatch_attr_activation
from aryx.api.ask_dispatch.ask_dispatch_attr_clear import _dispatch_attr_clear
from aryx.api.ask_dispatch.ask_dispatch_bulk_quantity import _dispatch_bulk_quantity_change
from aryx.api.ask_dispatch.ask_dispatch_change_request import (
    _dispatch_change_request,
    _dispatch_change_requests_multi,
    _dispatch_change_target_without_value,
)
from aryx.api.ask_dispatch.ask_dispatch_multi_select_removal import _dispatch_multi_select_removal
from aryx.api.ask_dispatch.ask_dispatch_quantity_country import (
    _dispatch_country_change,
    _dispatch_quantity_change,
)
from aryx.api.ask_dispatch.ask_dispatch_query_approval_decline import (
    _dispatch_approval,
    _dispatch_attr_query,
    _dispatch_decline,
    _dispatch_qa_question,
    _dispatch_response_mode_request,
)
from aryx.cpq.intent_schema import Confidence, IntentCategory, IntentResult


def _dispatch_intent_result(
    req: "Any", session: Any, attrs: list, result: IntentResult,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int = 0, classify_completion_tokens: int = 0,
    reader: Any = None, hints: dict | None = None,
) -> "dict[str, Any] | None":
    """Phase 2 (PARTIAL), docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md.

    Attempts to dispatch an LLM classification directly to the existing
    handler functions, bypassing the regex waterfall — returns None
    whenever it can't confidently do so, which the caller MUST treat as
    "fall through to the unchanged deterministic path," never as a
    terminal failure.

    IMPORTANT scoping note (found 2026-08-12): this function and the
    `gateway_classify_intent` call that feeds it have exactly ONE call
    site, nested inside the `session.status in ("awaiting_approval",
    "post_approval")` branch — a review-stage-only enhancement, never a
    general-purpose per-turn classifier.

    Confidence gating: LOW always returns None regardless of category.
    Several categories additionally require HIGH — see each sibling
    dispatcher's own docstring for why. Each category check below
    mirrors the original inline `if result.category == X and ...:` gate
    exactly — since a result carries exactly one category, delegating
    to the matching sibling preserves the original early-return
    semantics precisely.
    """
    if result.confidence == Confidence.LOW:
        return None

    if result.category == IntentCategory.AMBIGUOUS:
        return _dispatch_ambiguous(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.PRODUCT_QUANTITY_CHANGE:
        return _dispatch_quantity_change(
            result, req, session, reader, classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.COUNTRY_CHANGE:
        return _dispatch_country_change(
            result, req, session, reader, classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.OUT_OF_SCOPE:
        return _dispatch_out_of_scope(
            req, session, classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.CHANGE_REQUEST:
        return _dispatch_change_request(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.CHANGE_TARGET_WITHOUT_VALUE:
        return _dispatch_change_target_without_value(
            result, req, session, attrs, con_rules, bml_eval,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.CHANGE_REQUESTS_MULTI:
        return _dispatch_change_requests_multi(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.MULTI_SELECT_REMOVAL:
        return _dispatch_multi_select_removal(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.ATTR_ACTIVATION:
        return _dispatch_attr_activation(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.ATTR_CLEAR:
        return _dispatch_attr_clear(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.BULK_QUANTITY_CHANGE:
        return _dispatch_bulk_quantity_change(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.RESPONSE_MODE_REQUEST:
        return _dispatch_response_mode_request(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.ATTR_QUERY:
        return _dispatch_attr_query(
            result, req, session, attrs, con_rules, bml_eval,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.QA_QUESTION:
        return _dispatch_qa_question(
            result, req, session, attrs, reader,
            classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.APPROVAL:
        return _dispatch_approval(
            result, req, session, attrs, hiding_rules, rec_rules, con_rules, bml_eval,
            hints, classify_prompt_tokens, classify_completion_tokens,
        )
    if result.category == IntentCategory.DECLINE:
        return _dispatch_decline(
            result, req, session, classify_prompt_tokens, classify_completion_tokens,
        )

    # Every other category returns None — deliberately deferred rather
    # than rushed, so the deterministic path keeps owning them.
    return None
