"""STEP 6 bulk-quantity-change and multi-select-removal detection for the
awaiting_approval/post_approval review status, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Bulk quantity ("change
both the mounting types quantity to 67" targets every already-selected
row's quantity attr, never the grid selector's own value) must run
before the removal check (a different verb-and-verb-shape entirely) and
before the collision check that follows both. Logic unchanged from the
original inline block. `_cpq_engine` and every _handle_* helper below
are read through the ask_api module object (not imported by name) since
tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema_enums import IntentCategory

from aryx.api.ask_handle_bulk_quantity_change import _handle_bulk_quantity_change
from aryx.api import ask_handle_multi_select_removal as _ask_handle_multi_select_removal_module
from aryx.api import ask_shadow_classify_and_confirm_intent as _ask_shadow_classify_and_confirm_intent_module


def _step6_bulk_and_removal(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was a bulk quantity change
    or a multi-select removal; None otherwise, in which case the caller
    continues with the rest of the STEP 6 routing.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _bulk_qty_match = _cpq_engine.detect_bulk_quantity_change(
        req.question, attrs, session.filled_multi)
    if _bulk_qty_match:
        _bulk_selector_vn, _bulk_item_values, _bulk_new_qty = _bulk_qty_match
        return _handle_bulk_quantity_change(
            req, session, attrs, _bulk_selector_vn, _bulk_item_values, _bulk_new_qty,
            hiding_rules, rec_rules, con_rules,
        )

    _removal_match = _cpq_engine.detect_multi_select_removal(
        req.question, attrs, session.filled_multi)
    if _removal_match and _ask_shadow_classify_and_confirm_intent_module._llm_confirm_deterministic_intent(
        req, session, attrs, IntentCategory.MULTI_SELECT_REMOVAL,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        expected_variable_name=_removal_match[0].variable_name,
    ):
        _removal_attr, _to_remove = _removal_match
        return _ask_handle_multi_select_removal_module._handle_multi_select_removal(
            req, session, attrs, _removal_attr, _to_remove,
            hiding_rules, rec_rules, con_rules,
        )
    return None
