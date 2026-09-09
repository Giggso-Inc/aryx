"""Explicit "change country to X" command gate, split out of
`_run_cpq_turn_inner`'s pre-STEP-1 preamble (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md —
docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md follow-up).
Checked before hint extraction so it always takes priority over the
passive "first hint wins" anchor logic, and skipped while a
switch_country reprompt is already pending. The LLM decides the VALUE
too (docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md) — the regex detector
is only ever a cheap trigger for "is this worth confirming with the LLM
at all," never the source of the actual destination country. Logic
unchanged from the original inline block. Every ask_api name below is
read through the module object (not imported by name) since tests patch
several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.country.country_helpers import detect_country_change_request

from aryx.api.ask_response_building.ask_build_country_change_response import _build_country_change_response
from aryx.api.ask_llm.ask_llm_confirm_extract_country import _llm_confirm_and_extract_country
from aryx.api.ask_llm.ask_llm_confirm_extract_quantity import _build_llm_call_failed_response


def _preamble_country_change_gate(
    req: "Any", session: Any, reader: Any,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was an explicit country
    change command; None otherwise, in which case the caller continues.
    """
    _country_change_match = detect_country_change_request(req.question)
    if not (_country_change_match and session.pending_anchor != "switch_country"):
        return None
    _country_confirmed, _country_value, _country_call_failed = (
        _llm_confirm_and_extract_country(
            req, session, [],
            hiding_rules=[], rec_rules=[], con_rules=[], bml_eval=None, catalog_prefix="",
        )
    )
    if _country_confirmed:
        return _build_country_change_response(
            req, session, _country_value, reader=reader)
    if _country_call_failed:
        return _build_llm_call_failed_response(req, session)
    # else: rejected -- fall through to normal hint/attribute processing
    # below, exactly as if this gate never fired.
    return None
