"""Multi-attribute vs. single change-request dispatch for the
awaiting_approval/post_approval review status, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Multi-attribute first
("change X to A and Y to B" — up to detect_change_requests_multi's cap)
— only routes to the multi handler when it actually found 2+ distinct
attrs; a single match falls through to the existing, more heavily-tested
single-change path unchanged, so the common case has zero behavior
change. When 2+ multi matches are found, the single-change detector
never runs at all (same as the original inline if/else) — a None multi
result falls straight through to the caller's next stage, not into the
single-change path. Logic unchanged from the original inline block.
Every ask_api name below is read through the module object (not imported
by name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema_enums import IntentCategory

from aryx.api.ask_handle_cascade_multi import _handle_cascade_multi
from aryx.api.ask_intent_queue_text_helpers import _append_unmatched_targets_note, _scan_and_enqueue_remaining_targets
from aryx.api import ask_handle_cascade as _ask_handle_cascade_module
from aryx.api import ask_shadow_classify_and_confirm_intent as _ask_shadow_classify_and_confirm_intent_module


def _step6_change_dispatch(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was a multi- or
    single-attribute change request; None otherwise, in which case the
    caller continues with the rest of the STEP 6 routing.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _multi_matches = _cpq_engine.detect_change_requests_multi(
        req.question, attrs, session.filled, filled_multi=session.filled_multi)
    if len(_multi_matches) >= 2:
        _multi_vns = {a.variable_name for a, _ in _multi_matches}
        _scan_and_enqueue_remaining_targets(
            session, req.question, attrs, exclude_vns=_multi_vns,
        )
        _multi_result = _handle_cascade_multi(
            req, session, attrs, _multi_matches,
            hiding_rules, rec_rules, con_rules,
        )
        if _multi_result is not None:
            return _append_unmatched_targets_note(
                _multi_result, req.question, attrs,
                {a.variable_name for a, _ in _multi_matches},
            )
        return None

    change_result = _cpq_engine.detect_change_request(
        req.question, attrs, session.filled, filled_multi=session.filled_multi)
    if change_result and _ask_shadow_classify_and_confirm_intent_module._llm_confirm_deterministic_intent(
        req, session, attrs, IntentCategory.CHANGE_REQUEST,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        expected_variable_name=change_result[0].variable_name,
    ):
        changed_attr, new_value_hint = change_result
        # Enqueue sibling named targets before applying the primary.
        _scan_and_enqueue_remaining_targets(
            session, req.question, attrs,
            exclude_vns={changed_attr.variable_name},
        )
        return _append_unmatched_targets_note(
            _ask_handle_cascade_module._handle_cascade(
                req, session, attrs, changed_attr, new_value_hint,
                hiding_rules, rec_rules, con_rules,
            ),
            req.question, attrs, {changed_attr.variable_name},
        )
    return None
