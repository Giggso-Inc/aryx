"""Resolving WHICH quantity a dedicated quantity question/change targets
— the overall product quantity, a specific catalog attribute, or
genuinely ambiguous — split out of `_run_cpq_turn_inner`'s pre-STEP-1
preamble (Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md — docs/CPQ_QUANTITY_TARGET_MISROUTE_FIX_
PLAN_2026_08_17.md). A "competing candidate" must mean "something
genuinely present in the current configuration," not "theoretically
exists somewhere in the catalog." The deterministic backstop only
intercepts the one case that's provably NEVER ambiguous: no candidate
was ever a genuine customer decision, AND the message doesn't even
loosely resemble naming one — deliberately permissive, since an
over-inclusive match here only means "ask the LLM instead of
defaulting," never a wrong deterministic route. Logic unchanged from the
original inline block. Every ask_api name below is read through the
module object (not imported by name) since tests patch several of them
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_llm.ask_llm_resolve_quantity_target import _llm_resolve_quantity_target, _quantity_message_might_name_candidate
from aryx.raven_log import raven_log


def _preamble_resolve_quantity_target(
    req: "Any", session: Any, qty_pre: dict,
) -> "tuple[str | None, list]":
    """Returns (qty_target, qty_candidates). `qty_target` is "product",
    a specific attr's variable_name, or None (genuinely ambiguous).
    """
    from aryx.api import ask_api as _ask_api_module
    logger = _ask_api_module.logger
    _qty_candidates = [
        a for a in qty_pre["candidates"]
        if a.variable_name in session.filled
        or a.variable_name in session.filled_multi
    ]
    if not _qty_candidates:
        raven_log("DEBUG", "P4", "ask.preamble.quantity_target resolved to product, no filled candidates",
                  context={
                      "selected_option": "product", "available_options": ["product", "attr", "ambiguous"],
                      "reason_code": "NO_FILLED_CANDIDATE", "llm_consulted": False,
                      "catalog_candidate_count": len(qty_pre.get("candidates") or []),
                      "turn": getattr(session, "turn", None)})
        return "product", _qty_candidates

    _qty_provenance = [
        (a.variable_name, session.filled_source.get(a.variable_name))
        for a in _qty_candidates
    ]
    _qty_has_user_sourced = any(src == "user" for _vn, src in _qty_provenance)
    _qty_maybe_named = any(
        _quantity_message_might_name_candidate(req.question, a)
        for a in _qty_candidates
    )
    if not _qty_has_user_sourced and not _qty_maybe_named:
        logger.info(
            "cpq quantity gate: deterministic backstop -- no "
            "user-sourced or plausibly-named candidate, "
            "resolving straight to product without an LLM "
            "call run_id=%s candidates=%s",
            session.run_id, _qty_provenance,
        )
        raven_log("DEBUG", "P4", "ask.preamble.quantity_target resolved to product by deterministic backstop",
                  context={
                      "selected_option": "product", "available_options": ["product", "attr", "ambiguous"],
                      "reason_code": "NO_USER_SOURCED_OR_NAMED_CANDIDATE", "llm_consulted": False,
                      "candidate_provenance": [list(p) for p in _qty_provenance],
                      "turn": getattr(session, "turn", None)})
        return "product", _qty_candidates

    _qty_target = _llm_resolve_quantity_target(
        req.question, _qty_candidates, session, req.workspace_id,
    )
    if _qty_target == "product" and not _qty_has_user_sourced:
        logger.info(
            "cpq quantity gate: resolved to product despite "
            "non-user-sourced candidate(s) present "
            "run_id=%s candidates=%s",
            session.run_id, _qty_provenance,
        )
    elif (
        _qty_target not in (None, "product")
        and session.filled_source.get(_qty_target) != "user"
    ):
        logger.info(
            "cpq quantity gate: resolved to non-user-sourced "
            "candidate %r (source=%r) run_id=%s candidates=%s",
            _qty_target, session.filled_source.get(_qty_target),
            session.run_id, _qty_provenance,
        )
    raven_log("DEBUG", "P4", "ask.preamble.quantity_target resolved by LLM", context={
        "selected_option": "product" if _qty_target == "product"
        else "ambiguous" if _qty_target is None else "attr",
        "available_options": ["product", "attr", "ambiguous"],
        "reason_code": "LLM_RESOLVED_TARGET", "llm_consulted": True,
        "target_variable": _qty_target, "has_user_sourced": _qty_has_user_sourced,
        "maybe_named": _qty_maybe_named,
        "candidate_provenance": [list(p) for p in _qty_provenance],
        "turn": getattr(session, "turn", None)})
    return _qty_target, _qty_candidates
