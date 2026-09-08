""""What are the options for X?" response builder, and the LLM-first
classification usage-merger, split out of `ask_api.py` (final sweep,
Phase 11/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). `_build_attr_query_response` was factored out of
the regex path (docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_
12.md Phase 2) so `_dispatch_intent_result`'s `ATTR_QUERY` branch can
share the exact same response shape. `_with_classify_usage` adds the
LLM-first classification call's real token usage into an already-built
response dict and relabels the model fields so the UI can tell the
response was actually driven by an LLM call — a no-op when there's
nothing to add (classification hit the durable/in-memory cache path).
Logic unchanged from the original inline definitions. `_cpq_engine` and
`_persist_cpq_history` are read through the ask_api module object (not
imported by name) since tests patch several ask_api names by dotted
path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _build_attr_query_response(
    req: "Any", session: Any, attrs: list, con_rules: list, bml_eval: Any,
    queried_attr: Any,
) -> dict[str, Any]:
    """"What are the options for X?" response."""
    _cpq_engine = _ask_api_module._cpq_engine
    _queried_constrained = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval, filled_multi=session.filled_multi)
    options_block = _cpq_engine.next_question_prompt(
        queried_attr,
        constrained_item_values=_queried_constrained.get(queried_attr.entity_id),
        attrs=attrs,
    )
    current_val = session.filled.get(queried_attr.variable_name)
    current_note = (
        f"\n\n*Currently set to: **{session.display_filled.get(queried_attr.variable_name, current_val)}***"
        if current_val else ""
    )
    answer = (
        f"Here are the available values for "
        f"**{_cpq_engine.disambiguated_label(queried_attr, attrs)}**:"
        f"\n\n{options_block}{current_note}"
        f"\n\nReply with your choice and I'll update the configuration."
    )
    other_pending = [v for v in session.pending_variables if v != queried_attr.variable_name]
    session.pending_variables = [queried_attr.variable_name] + other_pending
    session.last_qa_variables = [queried_attr.variable_name]
    _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [queried_attr.variable_name],
        "tools_called": [f"cpq_attr_query({queried_attr.variable_name})"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }


def _with_classify_usage(
    result_dict: "dict[str, Any] | None", prompt_tokens: int, completion_tokens: int,
) -> "dict[str, Any] | None":
    """Adds the LLM-first classification call's real token usage into an
    already-built response dict. A no-op when result_dict is None or
    when there's nothing to add.
    """
    if result_dict is None or (not prompt_tokens and not completion_tokens):
        return result_dict
    usage = result_dict.get("usage") or {}
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + prompt_tokens
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + completion_tokens
    usage["menial_model"] = "cpq-llm-first"
    result_dict["usage"] = usage
    return result_dict
