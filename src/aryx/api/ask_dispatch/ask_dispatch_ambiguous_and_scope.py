"""AMBIGUOUS and OUT_OF_SCOPE branches of `_dispatch_intent_result`, split
out of `api/ask_api.py` (Phase 7/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline `if` blocks. `_cpq_engine`, `_persist_cpq_history`, and
`_with_classify_usage` are read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_pending_clarify.ask_pending_clarify_answer import _set_pending_clarify_and_answer


def _dispatch_ambiguous(
    result: Any, req: "Any", session: Any, attrs: list,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any] | None:
    """AMBIGUOUS: answered directly with the LLM's own clarifying_question
    — no session mutation, no config-mutating risk.
    """
    from aryx.api import ask_api as _ask_api_module
    if not result.clarifying_question:
        return None
    # docs/config_consistency_issues_2026-07-30.md issue 1 — an attribute
    # currently hidden for this product (e.g. modelSelectionFrequency
    # BandMsl_astro on a Single-Band order) must never be offered as a
    # disambiguation candidate, no matter how well it scores.
    _hidden_vns = _ask_api_module._cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval, filled_multi=session.filled_multi,
    )[2]
    # Persist grounded pending_clarify so the next bare reply (e.g.
    # "Hardware Version") resolves instead of falling to the nudge.
    return _set_pending_clarify_and_answer(
        req, session, attrs,
        original_question=req.question,
        clarifying_question=result.clarifying_question,
        con_rules=con_rules,
        bml_eval=bml_eval,
        prompt_tokens=classify_prompt_tokens,
        completion_tokens=classify_completion_tokens,
        tool_name="cpq_llm_first_ambiguous()",
        hidden_vns=_hidden_vns,
        hiding_rules=hiding_rules,
        rec_rules=rec_rules,
    )


def _dispatch_out_of_scope(
    req: "Any", session: Any,
    classify_prompt_tokens: int, classify_completion_tokens: int,
) -> dict[str, Any]:
    """OUT_OF_SCOPE: the same plain refusal wording `_llm_classify_
    is_cpq_question`'s negative case already uses.
    """
    answer = (
        "That's outside what I track here — product configuration and "
        "quoting. Happy to help with anything about your current quote."
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return _with_classify_usage({
        "answer": answer, "terms": [], "tools_called": ["cpq_llm_first_out_of_scope()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }, classify_prompt_tokens, classify_completion_tokens)
