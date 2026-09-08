"""LLM-first confirm-AND-extract for PRODUCT_QUANTITY_CHANGE, and the
shared "classifier call itself failed" response, split out of
`ask_api.py` (final sweep, Phase 11/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md —
docs/CPQ_QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md). Sibling of
`_llm_confirm_deterministic_intent`, extended: reuses the exact same
`gateway_classify_intent` call this checkpoint already makes, and
returns the LLM's own `quantity_text` when usable instead of trusting a
deterministic mis-parse unconditionally once confirmed. `_build_llm_
call_failed_response` is factored out (review finding, 2026-08-13) so
the turn-1 router-timeout site and this module's own mid-conversation
site can't drift into two different failure messages/tool names. Logic
unchanged from the original inline definitions. Every ask_api name
below is read through the module object (not imported by name) since
tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema import IntentCategory, _is_signed_digit_quantity_text

from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _llm_confirm_and_extract_quantity(
    req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any, catalog_prefix: str,
    fallback_value: int | None, fallback_decimal: str | None,
) -> tuple[bool, int | None, str | None]:
    """Returns (confirmed, value, decimal_value):
      - confirmed=False -- LLM disagreed on category, or the call
        failed/timed out. Caller MUST fall through to normal processing,
        never act on the deterministic match either.
      - confirmed=True, value=<int> -- the LLM's own `quantity_text` was
        a valid digit string; THIS is the value to use.
      - confirmed=True, value=None -- the LLM confirmed the category but
        its `quantity_text` wasn't usable; caller falls back to
        `fallback_value`/`fallback_decimal`.
    """
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger
    try:
        decision = _ask_api_module.gateway_classify_intent(
            req.question, attrs, session, _ask_api_module._cpq_engine, req.workspace_id,
            hiding_rules=hiding_rules, rec_rules=rec_rules, con_rules=con_rules,
            bml_eval=bml_eval, catalog_prefix=catalog_prefix,
        )
    except Exception as exc:  # noqa: BLE001 — reject on any failure, never guess
        logger.debug(
            "cpq llm_first_quantity: gateway call failed, rejecting: %r", exc,
        )
        return False, None, None
    result = decision.result
    if result is None or result.intent_category != IntentCategory.PRODUCT_QUANTITY_CHANGE:
        return False, None, None
    # `.isdigit()` rejects a leading "-", which would silently make a
    # genuinely negative LLM-reported quantity ("-5") fall through to
    # the fallback instead of being used -- same bug as `intent_schema.
    # py`'s `validate_gateway_quarantine`, fixed there via the same
    # helper.
    if _is_signed_digit_quantity_text(result.quantity_text):
        return True, int(result.quantity_text), None
    return True, fallback_value, fallback_decimal


def _build_llm_call_failed_response(req: "Any", session: Any) -> dict[str, Any]:
    """Shared "the classifier call itself failed" response — owner
    directive: a customer told the truth instead of a silent regex
    fallback, or a generic re-ask that reads as if they said nothing.
    """
    answer = (
        "Sorry — I couldn't process that just now (a classifier "
        "call failed). Please try again in a moment."
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_llm_call_failed()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
