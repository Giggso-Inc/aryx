"""Scoped re-ask response builders for a pending scope question, split
out of `ask_api.py` (final sweep, Phase 11/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_resolve_scope_reply` is the single integration point replacing a bare
`resolve_against_scope` call wherever a reply to an ACTIVE pending scope
question is resolved (docs/CPQ_PRODUCT_SCOPE_LLM_FIRST_PLAN_2026_08_13.
md) — LLM classifies first, the deterministic ladder validates second;
any outcome other than a confirmed "candidate" falls through to running
the ladder on the ORIGINAL reply, so this function can only ever ADD
coverage, never remove it. `_scoped_reask_response` never widens back to
the full catalog on a miss. `_build_scope_skip_response` and `_build_
scope_family_only_response` are owner decisions: never auto-pick a
default or a variant for the customer, just ask plainly. Logic unchanged
from the original inline definitions. `_persist_cpq_history` is read
through the ask_api module object (not imported by name) since tests
patch it by dotted path.
"""

from __future__ import annotations

from typing import Any, Literal

from aryx.api.ask_llm.ask_llm_classify_scope_reply import _llm_classify_scope_reply
from aryx.cpq.pending_scope import (
    ScopeResolve,
    format_did_you_mean,
    is_confident_scope_suggestion,
    log_scope_retained,
    resolve_against_scope,
    scope_loop_exit_threshold,
)

from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _scoped_reask_response(
    req: "Any",
    session: Any,
    reply: str,
    *,
    scope_label: str = "",
    tools_called: str = "cpq_scope_reask()",
) -> dict[str, Any]:
    """Build a scoped 'did you mean' / numbered re-ask; retain scope."""
    cands = list(session.pending_scope_candidates or [])
    res = resolve_against_scope(reply, cands)
    session.pending_scope_misses = int(session.pending_scope_misses or 0) + 1
    log_scope_retained(
        run_id=getattr(session, "run_id", "") or "",
        reply=reply,
        kind=session.pending_scope_kind or "",
        n_candidates=len(cands),
        suggestions=res.suggestions,
        misses=session.pending_scope_misses,
    )
    numbered = session.pending_scope_misses >= scope_loop_exit_threshold()
    sug = res.suggestions or cands[:3]
    confident_single = len(sug) == 1 and is_confident_scope_suggestion(res)
    if numbered:
        sug = cands  # full same-scope list, never catalog-wide
    elif len(sug) == 1 and not confident_single:
        # A single suggestion that only cleared the bare fuzzy-suggest
        # floor is coincidental overlap, not a real near-miss (confirmed
        # live 2026-08-08 -- see is_confident_scope_suggestion's own
        # docstring). Show the real full list instead of framing that one
        # weak guess as "did you mean X?".
        sug = cands
    answer = format_did_you_mean(
        reply, sug, numbered=numbered, scope_label=scope_label,
        confident_single=confident_single,
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": [tools_called],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _resolve_scope_reply(
    reply: str, candidates: list[str], scope_label: str,
    session: Any, workspace_id: int,
) -> "ScopeResolve | Literal['skip', 'family_only']":
    """Single integration point replacing a bare `resolve_against_scope`
    call wherever a reply to an ACTIVE pending scope question is being
    resolved (docs/CPQ_PRODUCT_SCOPE_LLM_FIRST_PLAN_2026_08_13.md).
    """
    outcome, guess = _llm_classify_scope_reply(reply, candidates, scope_label, session, workspace_id)
    if outcome in ("skip", "family_only"):
        return outcome
    if outcome == "candidate" and guess:
        res = resolve_against_scope(guess, candidates)
        if res.tier != "miss":
            return res
    return resolve_against_scope(reply, candidates)


def _build_scope_skip_response(
    req: "Any", session: Any, candidates: list[str], scope_label: str,
    tools_called: str = "cpq_scope_skip_declined()",
) -> dict[str, Any]:
    """Response for a reply classified as asking to skip/defer a pending
    scope question. Owner decision: ask what they'd like to do instead —
    never auto-pick a default, never silently escalate.
    """
    lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(candidates))
    answer = (
        f"This choice determines the rest of the configuration, so I "
        f"can't skip it yet — could you tell me which **{scope_label}** "
        f"you'd like, or what you're trying to configure? Here are the "
        f"choices again:\n\n{lines}"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": [tools_called],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _build_scope_family_only_response(
    req: "Any", session: Any, candidates: list[str], scope_label: str,
    tools_called: str = "cpq_scope_family_only()",
) -> dict[str, Any]:
    """Response for a reply that's clearly on-topic but names only the
    broader family/category, not a specific option — owner decision:
    never auto-pick a variant for them, just tell them plainly to
    choose one so the quote can proceed. Distinct wording from a
    genuine miss (`_scoped_reask_response`) since the reply itself
    wasn't wrong, just not specific enough yet.
    """
    lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(candidates))
    answer = (
        f"To proceed with the quote, please select the specific "
        f"**{scope_label}** from the list below:\n\n{lines}"
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": [tools_called],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
