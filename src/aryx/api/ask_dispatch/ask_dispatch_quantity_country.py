"""PRODUCT_QUANTITY_CHANGE and COUNTRY_CHANGE branches of `_dispatch_
intent_result`, split out of `api/ask_api.py` (Phase 7/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline `if` blocks. `_cpq_engine` and `_with_
classify_usage` are read through the ask_api MODULE object (not imported
by name) since ask_api tests patch several of its own module-level names
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_response_building.ask_build_country_change_response import _build_country_change_response
from aryx.api.ask_response_building.ask_build_product_quantity_response import (
    _build_product_quantity_change_response,
)
from aryx.cpq.intent_schema.intent_schema import _is_signed_digit_quantity_text


def _dispatch_quantity_change(
    result: Any, req: "Any", session: Any, reader: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """PRODUCT_QUANTITY_CHANGE (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md
    §8 Phase 4): session-level, no-target category -- quantity_description
    is already validated (signed-digits-only) by validate_gateway_
    quarantine before this function ever sees it, so no further
    resolution step is needed, unlike attribute-targeting categories.
    Shares the exact same response-building helper the deterministic
    gate (ask_api.py, mid-turn) already uses.

    Review finding, 2026-08-13 (docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_
    13.md follow-up): this used to check `_qty.isdigit()`, which rejects
    a leading "-" -- the exact bug `_is_signed_digit_quantity_text` was
    introduced to fix in `validate_gateway_quarantine` (docs/CPQ_
    QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md). Quarantine already
    allows a genuinely negative `quantity_text` through (so
    `is_valid_product_quantity` can reject it with a clear message
    rather than the LLM's answer being silently discarded), but this
    duplicate check downstream still used the plain built-in, silently
    dropping a confirmed negative-quantity dispatch instead of routing
    it to `_build_product_quantity_change_response`'s own range
    rejection message.
    """
    if not result.quantity_description:
        return None
    _qty = result.quantity_description.strip()
    if not _is_signed_digit_quantity_text(_qty):
        return None
    return _with_classify_usage(
        _build_product_quantity_change_response(
            req, session, reader, value=int(_qty),
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )


def _dispatch_country_change(
    result: Any, req: "Any", session: Any, reader: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """COUNTRY_CHANGE (docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md §8
    Phase 4).

    ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_
    17.md): a 4th, previously-unidentified country-setting path --
    distinct from `_llm_confirm_and_extract_country` (the one this
    plan's Path C originally targeted) and only reachable when
    `detect_country_change_request`'s regex fails to structurally
    match at all (confirmed live: "change country to U.S.A" -- the
    periods break both of `_COUNTRY_CHANGE_RE`'s capture
    alternatives, so that gate never even fires, and THIS universal
    LLM-first dispatcher handles it instead). Canonicalize here too,
    via the same generic alias-group resolution every other country
    path now uses, so this path can't reintroduce the "US.A"/
    "U.S.A"-class bug through its own separate route.
    """
    from aryx.api import ask_api as _ask_api_module
    if not result.country_description:
        return None
    _canonical_country_description = (
        _ask_api_module._cpq_engine.is_recognized_country(result.country_description)
        or result.country_description
    )
    return _with_classify_usage(
        _build_country_change_response(
            req, session, _canonical_country_description, reader=reader,
        ),
        classify_prompt_tokens, classify_completion_tokens,
    )
