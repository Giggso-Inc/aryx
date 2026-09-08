"""LLM-first confirm-AND-extract for COUNTRY_CHANGE, split out of
`ask_api.py` (final sweep, Phase 11/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md — docs/CPQ_COUNTRY_LLM_
ONLY_PLAN_2026_08_13.md). Sibling of `_llm_confirm_and_extract_
quantity`, but simpler: `validate_gateway_quarantine` already REJECTS
any COUNTRY_CHANGE result whose `country_text` isn't a real, recognized
country before it ever reaches here, so a CONFIRMED result is
guaranteed to carry a valid country — there is no fallback branch and
no deterministic regex value ever consulted. `detect_country_change_
request` (the caller's own regex) may only ever be used as a cheap
trigger for whether to make this call at all, never as the value. Logic
unchanged from the original inline definition. Every ask_api name below
is read through the module object (not imported by name) since tests
patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_schema import IntentCategory

from aryx.api import ask_api as _ask_api_module

# Gateway failure reasons (GatewayDecision.reason) meaning the LLM call
# itself never produced a usable classification -- distinct from a real
# disagreement (a confirmed-but-different category, or a confirmed
# category whose value didn't pass quarantine). Review finding, 2026-08-13:
# collapsing both into the same `confirmed=False` made a mid-conversation
# timeout indistinguishable from a normal "the LLM looked and disagreed",
# so the explicit "classifier call failed" message only ever fired for
# turn-1 router failures, never here.
_GATEWAY_CALL_FAILURE_REASONS = frozenset({"timeout", "schema_fail", "empty_question"})


def _llm_confirm_and_extract_country(
    req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> tuple[bool, str | None, bool]:
    """Returns (confirmed, country, call_failed):
      - confirmed=True, country=<str>, call_failed=False -- the real
        destination country.
      - confirmed=False, country=None, call_failed=True -- the gateway
        call itself never produced a usable classification. Caller
        should surface the "classifier call failed" message.
      - confirmed=False, country=None, call_failed=False -- the call
        succeeded but classified as a different category, or a confirmed
        result still somehow lacked a usable country (defensive only).
        Caller must never fall back to a regex-captured value, and
        should fall through to normal processing.
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
            "cpq llm_first_country: gateway call failed, rejecting: %r", exc,
        )
        return False, None, True
    if decision.action == "fallback" and decision.reason in _GATEWAY_CALL_FAILURE_REASONS:
        return False, None, True
    result = decision.result
    if result is None or result.intent_category != IntentCategory.COUNTRY_CHANGE:
        return False, None, False
    # ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md):
    # `is_recognized_country` now returns the resolved canonical name (e.g.
    # "United States") instead of a bare bool — return THAT, not the LLM's
    # raw `country_text`, so a punctuation/abbreviation variant the LLM
    # copied verbatim ("U.S.A") still lands in session.country in clean
    # canonical form, same as every other resolution path.
    _cpq_engine = _ask_api_module._cpq_engine
    canonical_country = result.country_text and _cpq_engine.is_recognized_country(
        result.country_text,
    )
    if canonical_country:
        return True, canonical_country, False
    return False, None, False
