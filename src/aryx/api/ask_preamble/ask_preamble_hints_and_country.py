"""Natural-language hint extraction and country resolution (Step 1
prerequisite), split out of `_run_cpq_turn_inner`'s pre-STEP-1 preamble
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md — docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md /
docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_17.md). Regex may
never decide WHAT the country is, only ever be a cheap trigger — a
direct reply to a JUST-asked country anchor question resolves
deterministic-first (alias table) then LLM-escalated-last-resort; a
fresh statement is sourced ONLY from the turn-1 unified
`route_meta.country` extraction, never a regex fallback.
`session.country` is "first hint wins, never re-derived" — only ITS
assignment is guarded against a bad extractor match, never
`hints["country"]` itself. Also stashes the full order utterance early
(even before family resolves) so a later short family reply does not
lose country/customer context. Logic unchanged from the original inline
block. `_cpq_engine` is read through the ask_api module object (not
imported by name) since at least one test replaces the whole singleton
via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.intent_gateway.intent_gateway import soft_quote_heuristic
from aryx.raven_log import raven_log

from aryx.api.ask_llm.ask_llm_extract_quantity_and_country_reply import _llm_resolve_bare_country_reply


def _preamble_extract_hints_and_resolve_country(
    req: "Any", session: Any, route_meta: "Any | None",
) -> "tuple[dict, bool]":
    """Mutates `session` in place (country, product_anchor_question).
    Returns (hints, country_llm_call_failed).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _country_llm_call_failed = False
    hints = _cpq_engine.extract_hints(req.question)
    hints.pop("country", None)

    if session.pending_anchor == "country":
        _bare_country_reply = req.question.strip()
        _resolved_bare_country = _cpq_engine.is_recognized_country(_bare_country_reply)
        if not _resolved_bare_country:
            _resolved_bare_country = _llm_resolve_bare_country_reply(
                _bare_country_reply, req.workspace_id,
            )
        hints["country"] = _resolved_bare_country or _bare_country_reply
    elif route_meta is not None:
        if route_meta.country:
            hints["country"] = (
                _cpq_engine.is_recognized_country(route_meta.country)
                or route_meta.country
            )
        elif route_meta.timed_out or route_meta.error:
            _country_llm_call_failed = True

    _recognized_country = hints.get("country") and _cpq_engine.is_recognized_country(
        hints["country"],
    )
    if (
        "country" in hints and not session.country
        and _recognized_country
    ):
        session.country = _recognized_country
    elif (session.country and "country" not in hints
          and session.pending_anchor != "switch_country"):
        hints["country"] = session.country

    if (
        (session.country or soft_quote_heuristic(req.question) or "country" in hints)
        and (
            not session.product_anchor_question
            or len(req.question.strip()) > len(session.product_anchor_question.strip())
        )
    ):
        session.product_anchor_question = req.question

    raven_log("DEBUG", "P4", "ask.preamble.hints hints and country resolved", context={
        "hint_names": sorted(hints.keys()),
        "country": hints.get("country") or session.country or "",
        "country_valid": bool(_recognized_country),
        "country_source": (
            "pending_anchor_reply" if session.pending_anchor == "country"
            else "route_meta" if (route_meta is not None and route_meta.country)
            else "session" if session.country else "none"),
        "country_llm_call_failed": _country_llm_call_failed,
        "session_country_set": bool(session.country), "turn": session.turn,
    })
    return hints, _country_llm_call_failed
