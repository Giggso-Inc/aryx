"""Phase 1 shadow-mode universal-intent classification, and the blanket
LLM-as-final-verdict checkpoint for a deterministic-detector proposal,
split out of `ask_api.py` (final sweep, Phase 11/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_shadow_classify_cpq_turn` is called once per turn, read-only: it NEVER
returns anything to the caller, NEVER mutates `session`, and is wrapped
in a bare try/except so any failure is invisible to the actual turn
(docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md Phase 1). `_llm_confirm_
deterministic_intent` is reject-on-failure, deliberately: any exception,
a `None` result, or a disagreeing category/variable_name all return
False — this NEVER falls back to "trust the deterministic match
anyway" (docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md
follow-up). Logic unchanged from the original inline definitions. Every
ask_api name below is read through the module object (not imported by
name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema import IntentCategory

from aryx.api import ask_api as _ask_api_module


def _shadow_classify_cpq_turn(
    req: "Any", session: Any, attrs: list,
) -> None:
    """Phase 1 shadow-mode hook. Correlated with the real turn's outcome
    by run_id: `run_ask` logs the actual `tools_called`/category right
    after `_run_cpq_turn` returns, tagged with the same `session.run_id`
    this logs.
    """
    logger = _ask_api_module.logger
    try:
        result, _it, _ot = _ask_api_module._llm_classify_intent_universal(
            req.question, attrs, session, req.workspace_id)
        if result is None:
            logger.info(
                "cpq_shadow_intent: message %r -> classification failed/unparseable",
                req.question,
            )
            return
        resolved_summary = []
        for t in ([result.target] if result.target else result.targets):
            attr, candidates = _ask_api_module._resolve_target_description(t.target_description, attrs)
            resolved_summary.append({
                "target_description": t.target_description,
                "resolved_vn": attr.variable_name if attr else None,
                "candidate_count": len(candidates),
            })
        logger.info(
            "cpq_shadow_intent: message %r -> category=%s confidence=%s "
            "resolved=%s clarifying_question=%r rationale=%r",
            req.question, result.category.value, result.confidence.value,
            resolved_summary, result.clarifying_question, result.rationale,
        )
    except Exception:  # noqa: BLE001 — shadow diagnostic must never affect the turn
        logger.debug("cpq_shadow_intent: diagnostic failed", exc_info=True)


def _llm_confirm_deterministic_intent(
    req: "Any", session: Any, attrs: list, expected_category: IntentCategory,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any, catalog_prefix: str,
    expected_variable_name: str | None = None,
) -> bool:
    """Blanket LLM-as-final-verdict checkpoint. Calls the SAME existing
    classifier fresh, independently, and requires it to agree with the
    deterministic candidate before the caller is allowed to act on it.
    """
    logger = _ask_api_module.logger
    try:
        decision = _ask_api_module.gateway_classify_intent(
            req.question, attrs, session, _ask_api_module._cpq_engine, req.workspace_id,
            hiding_rules=hiding_rules, rec_rules=rec_rules, con_rules=con_rules,
            bml_eval=bml_eval, catalog_prefix=catalog_prefix,
        )
    except Exception as exc:  # noqa: BLE001 — reject on any failure, never guess
        logger.debug(
            "cpq llm_verdict_checkpoint: gateway call failed, rejecting "
            "deterministic match: %r", exc,
        )
        return False
    result = decision.result
    if result is None or result.intent_category != expected_category:
        return False
    if expected_variable_name is not None and result.variable_name != expected_variable_name:
        return False
    return True
