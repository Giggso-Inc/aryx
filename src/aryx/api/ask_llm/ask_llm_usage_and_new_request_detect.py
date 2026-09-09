"""Real per-turn LLM usage application, and detecting whether a reply
to a pending question is actually a genuine new request instead, split
out of `ask_api.py` (final sweep, Phase 11/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`_apply_real_llm_usage` replaces a CPQ turn response's usage dict with
real totals, in place, when llm_runtime recorded any actual LLM call
during the turn — a no-op for a purely deterministic turn or an
early-return shape with no "usage" key (docs/CPQ_Usage_Reporting_Gap).
`_pending_reply_looks_like_new_request` is True only if the question has
an explicit change-verb/arrow AND names some OTHER real attr — shared by
STEP 5's own answer-lock and the LLM-first gateway's pre-STEP-5 gate
(docs/config_consistency_issues_2026-07-30.md issue 4 follow-up). Logic
unchanged from the original inline definitions. `_cpq_engine` is read
through the ask_api module object (not imported by name) since at least
one test replaces the whole singleton via `patch("aryx.api.ask_api.
_cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx import llm_runtime



def _apply_real_llm_usage(result: dict[str, Any]) -> None:
    """Replace a CPQ turn response's usage dict with real totals, in
    place, when llm_runtime recorded any actual LLM call during this
    turn. A no-op when nothing was recorded, or when `result` has no
    "usage" key at all.
    """
    if not isinstance(result, dict) or "usage" not in result:
        return
    real = llm_runtime.get_turn_usage()
    if not real or not real["calls"]:
        return
    models = ", ".join(real["models"]) or result["usage"].get("menial_model", "cpq-engine")
    result["usage"] = {
        "prompt_tokens": real["prompt_tokens"],
        "completion_tokens": real["completion_tokens"],
        "latency_ms": real["latency_ms"],
        "menial_model": models,
        "answer_model": models,
    }


def _pending_reply_looks_like_new_request(
    question: str, pending_attr: Any, attrs: list, filled: dict, filled_multi: dict,
) -> bool:
    """True only if `question` has an explicit change-verb/arrow AND
    names some OTHER real attr (never `pending_attr` itself) — i.e. a
    genuine new request, not a bare reply meant to answer the currently-
    pending question.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if pending_attr is None:
        return False
    other_attrs = [a for a in attrs if a.variable_name != pending_attr.variable_name]
    return bool(
        (_cpq_engine._CHANGE_VERB_RE.search(question)
         or _cpq_engine._ARROW_RE.search(question))
        and (
            _cpq_engine.detect_change_target_without_value(question, other_attrs, filled)
            or _cpq_engine.detect_change_request(
                question, other_attrs, filled, filled_multi=filled_multi)
            or _cpq_engine.detect_change_requests_multi(
                question, other_attrs, filled, filled_multi=filled_multi)
        )
    )
