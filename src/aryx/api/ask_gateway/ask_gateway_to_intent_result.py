"""Mapping a quarantined GatewayIntentResult onto IntentResult for
dispatch, split out of `api/ask_api.py` (Phase 7/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema.intent_schema import ChangeTarget, IntentCategory, IntentResult


def _gateway_to_intent_result(
    gw: Any,
    attrs: list,
    value_display: str | None,
) -> IntentResult | None:
    """Map a quarantined GatewayIntentResult onto IntentResult for dispatch.

    Uses candidate-resolved variable_name → display_label and value_ref →
    display_name (passed in as value_display). Never trusts free-text
    item_value from the model. Returns None for categories the existing
    _dispatch_intent_result does not yet handle (fall through).

    docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md Phase 1:
    `needs_target` previously only listed the 3 originally-wired
    categories, silently drifted from `IntentResult`'s own docstring
    contract (which already documented ATTR_ACTIVATION/ATTR_CLEAR/
    ATTR_QUERY/BULK_QUANTITY_CHANGE/MULTI_SELECT_REMOVAL as target-
    bearing) -- a missing target for any of these used to proceed
    silently with target=None instead of refusing the mapping. `targets`
    was also only ever populated for CHANGE_REQUESTS_MULTI despite the
    same docstring documenting it as shared with MULTI_SELECT_REMOVAL.
    Both closed here so the remaining dispatch-branch phases (2-4) have
    a converter that actually matches its own documented contract.
    """
    from aryx.cpq.intent_schema.intent_schema import GatewayIntentResult as _GIR
    if not isinstance(gw, _GIR):
        return None
    by_vn = {a.variable_name: a for a in attrs}
    target = None
    if gw.variable_name and gw.variable_name in by_vn:
        attr = by_vn[gw.variable_name]
        target = ChangeTarget(
            target_description=attr.display_label,
            new_value_description=value_display,
        )
    # Prefer gateway-selected display_label so _resolve_target_description
    # can exact-match; if no target and category needs one, refuse map.
    needs_target = gw.intent_category in {
        IntentCategory.CHANGE_REQUEST,
        IntentCategory.CHANGE_TARGET_WITHOUT_VALUE,
        IntentCategory.CHANGE_REQUESTS_MULTI,
        IntentCategory.ATTR_ACTIVATION,
        IntentCategory.ATTR_CLEAR,
        IntentCategory.ATTR_QUERY,
        IntentCategory.BULK_QUANTITY_CHANGE,
        IntentCategory.MULTI_SELECT_REMOVAL,
    }
    if needs_target and target is None:
        return None
    return IntentResult(
        category=gw.intent_category,
        confidence=gw.confidence,
        target=target,
        targets=[target] if (
            gw.intent_category in (
                IntentCategory.CHANGE_REQUESTS_MULTI,
                IntentCategory.MULTI_SELECT_REMOVAL,
            )
            and target is not None
        ) else [],
        quantity_description=(
            gw.quantity_text
            if gw.intent_category in (
                IntentCategory.BULK_QUANTITY_CHANGE,
                IntentCategory.PRODUCT_QUANTITY_CHANGE,
            )
            else None
        ),
        country_description=(
            gw.country_text
            if gw.intent_category == IntentCategory.COUNTRY_CHANGE
            else None
        ),
        response_mode=(
            gw.response_mode
            if gw.intent_category == IntentCategory.RESPONSE_MODE_REQUEST
            else None
        ),
        clarifying_question=gw.clarifying_question,
        rationale=gw.rationale,
    )
