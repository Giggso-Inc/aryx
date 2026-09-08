"""Attribute activation ("add X"/"activate X") and attribute nullify
("clear X"/"unset X") detection for the awaiting_approval/post_approval
review status, split out of `_run_cpq_turn_inner` (Phase 10/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Same priority position as the removal check that precedes both (D2/D4,
docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md) — distinct intents from a
normal value-replacement change request. Logic unchanged from the
original inline block. `_cpq_engine` and the _handle_* helpers below are
read through the ask_api module object (not imported by name) since
tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema_enums import IntentCategory

from aryx.api import ask_api as _ask_api_module


def _step6_activation_and_clear(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was an attribute activation
    or nullify; None otherwise, in which case the caller continues with
    the rest of the STEP 6 routing.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    _activation_match = _cpq_engine.detect_attr_activation(
        req.question, attrs, session.filled, session.filled_multi,
        hiding_rules, req.workspace_id, catalog_prefix, bml_eval=bml_eval,
    )
    if _activation_match and _ask_api_module._llm_confirm_deterministic_intent(
        req, session, attrs, IntentCategory.ATTR_ACTIVATION,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        expected_variable_name=_activation_match.variable_name,
    ):
        return _ask_api_module._handle_attr_activation(
            req, session, attrs, _activation_match,
            hiding_rules, rec_rules, con_rules,
        )

    _clear_match = _cpq_engine.detect_attr_clear(
        req.question, attrs, session.filled, rec_rules, con_rules, bml_eval=bml_eval,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
    )
    if _clear_match and _ask_api_module._llm_confirm_deterministic_intent(
        req, session, attrs, IntentCategory.ATTR_CLEAR,
        hiding_rules, rec_rules, con_rules, bml_eval, catalog_prefix,
        expected_variable_name=_clear_match.variable_name,
    ):
        return _ask_api_module._handle_attr_clear(
            req, session, attrs, _clear_match,
            hiding_rules, rec_rules, con_rules,
        )
    return None
