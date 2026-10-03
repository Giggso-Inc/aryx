"""Resolving a reply to a prior model-leaf disambiguation question,
split out of `_run_cpq_turn_inner`'s model-leaf disambiguation block
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_model_leaf_
resolve.py` under the line cap. Logic unchanged from the original
inline block. `_resolve_scope_reply`, `_build_scope_skip_response`,
`_build_scope_family_only_response`, and `_scoped_reask_response` are
read through the ask_api MODULE object (not imported by name) since
these are not yet split out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_scope_and_pending.ask_scope_reask_responses import _build_scope_family_only_response, _build_scope_skip_response, _resolve_scope_reply, _scoped_reask_response
from aryx.cpq.pending_scope.pending_scope import set_pending_scope
from aryx.raven_log import raven_log


def _resolve_pending_model_leaf_reply(
    req: "Any", session: Any,
) -> "tuple[str | None, dict[str, Any] | None]":
    """A prior turn already asked which model leaf was meant — this
    reply should answer it. LLM classifies first (docs/CPQ_PRODUCT_
    SCOPE_LLM_FIRST_PLAN_2026_08_13.md), deterministic ladder validates
    second; on miss, scoped re-ask (never the full Product 325-option
    list). Supersedes the old ConfigAttr-wrapping _llm_resolve_label_
    collision fallback this call site used to awkwardly reuse —
    _resolve_scope_reply already covers that same job, natively, for
    plain strings.

    Returns (resolved_leaf, early_return_response) — `early_return_
    response` is non-None when this turn is fully handled (a scope
    skip/family_only response, or a scoped re-ask); the caller must
    return it immediately when present.
    """
    _reply = req.question.strip()
    _leaf_scope = list(session.pending_model_leaf_candidates)
    _scope_reply = _resolve_scope_reply(
        _reply, _leaf_scope, "product line", session, req.workspace_id,
    )
    if _scope_reply == "skip":
        raven_log("INFO", "P4", "ask.model_leaf.pending_reply customer skipped product-line choice", context={
            "selected_option": "skip", "available_options": ["skip", "family_only", "picked", "reask"],
            "reason_code": "SCOPE_REPLY_SKIP", "candidate_count": len(_leaf_scope),
            "reply_len": len(_reply), "turn": getattr(session, "turn", None)})
        return None, _build_scope_skip_response(
            req, session, _leaf_scope, "product line",
        )
    if _scope_reply == "family_only":
        raven_log("INFO", "P4", "ask.model_leaf.pending_reply customer chose family only", context={
            "selected_option": "family_only", "available_options": ["skip", "family_only", "picked", "reask"],
            "reason_code": "SCOPE_REPLY_FAMILY_ONLY", "candidate_count": len(_leaf_scope),
            "reply_len": len(_reply), "turn": getattr(session, "turn", None)})
        return None, _build_scope_family_only_response(
            req, session, _leaf_scope, "product line",
        )
    _sres = _scope_reply
    resolved_leaf = _sres.matched if _sres.matched else None
    raven_log("INFO" if resolved_leaf is None else "DEBUG", "P4",
              "ask.model_leaf.pending_reply product-line reply matched against candidates", context={
                  "selected_option": "reask" if resolved_leaf is None else "picked",
                  "available_options": ["skip", "family_only", "picked", "reask"],
                  "reason_code": "NO_CANDIDATE_MATCHED" if resolved_leaf is None else "CANDIDATE_MATCHED",
                  "picked_leaf": resolved_leaf, "candidate_count": len(_leaf_scope),
                  "candidates": list(_leaf_scope), "reply_len": len(_reply),
                  "turn": getattr(session, "turn", None)})
    if resolved_leaf is None:
        # Keep model-leaf candidates AND pending_scope in sync
        set_pending_scope(
            session,
            kind="family_disambiguation",
            candidates=_leaf_scope,
            origin_question=req.question,
            attr_vn="",
            asked_turn=session.turn,
        )
        return None, _scoped_reask_response(
            req, session, _reply,
            scope_label="product line",
            tools_called="cpq_model_leaf_ambiguous()",
        )
    return resolved_leaf, None
