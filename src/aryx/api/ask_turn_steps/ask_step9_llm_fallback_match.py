"""STEP 5 LLM fallback for an unmatched pending answer, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md — Gap A/Amendment 2).
Fragment-match found nothing — try the shared Tier-2 LLM fallback
before giving up, scoped to only this attr's own options. Single-select
only: apply_multi_answer already scans for multiple named options, so a
multi-select miss is a genuine no-match, not a long-sentence problem.
A "low" confidence pick surfaces its candidates for the caller to ask
about instead of silently guessing between real options. Logic
unchanged from the original inline block. `_llm_resolve_pending_answer`
is read through the ask_api module object (not imported by name) since
at least one test replaces it via `patch.object(api, "_llm_resolve_
pending_answer", ...)`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_llm_resolve_pending_answer as _ask_llm_resolve_pending_answer_module


def _step9_llm_fallback_match(
    req: "Any", pending_attr: Any, pending_constrained: list | None,
    scope_for_attr: bool, scope_cands: list, result: Any,
) -> "tuple[Any, list | None]":
    """Returns (result, llm_low_confidence_candidates) — `result` is
    passed through unchanged when it was already truthy, or already None
    when the attr is a multi-select (this fallback never runs for those).
    """
    _llm_low_confidence_candidates = None
    if result or pending_attr.select_type == "multi":
        return result, _llm_low_confidence_candidates

    _llm_pick = _ask_llm_resolve_pending_answer_module._llm_resolve_pending_answer(req.question, pending_attr, req.workspace_id)
    if _llm_pick and _llm_pick["confidence"] == "high":
        _iv = _llm_pick["iv"]
        _in_constrained = pending_constrained is None or _iv in pending_constrained
        _in_remembered_scope = (
            not scope_for_attr
            or _iv in scope_cands
            or _llm_pick["disp"] in scope_cands
        )
        if _in_constrained and _in_remembered_scope:
            result = (_llm_pick["iv"], _llm_pick["disp"])
    elif _llm_pick and _llm_pick["confidence"] == "low":
        _cands = _llm_pick["candidates"]
        if pending_constrained is not None:
            _allowed_disp = {
                o.display_name for o in pending_attr.options
                if o.item_value in pending_constrained
            }
            _cands = [c for c in _cands if c in _allowed_disp]
        if scope_for_attr:
            _cands = [c for c in _cands if c in scope_cands]
        _llm_low_confidence_candidates = _cands or None
    return result, _llm_low_confidence_candidates
