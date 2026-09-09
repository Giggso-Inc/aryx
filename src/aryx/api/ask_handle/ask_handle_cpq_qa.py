"""STEP 7 — Contextual Q&A handler, split out of `api/ask_api.py` (Phase
8/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-
09-03.md). Logic unchanged from the original inline definition; every
stage lives in a sibling `ask_qa_*.py` file purely to keep this file
under the line cap. `_persist_cpq_history` is read through the ask_api
MODULE object (not imported by name) since ask_api tests patch several
of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_qa.ask_qa_fast_path import _qa_fast_path_or_enumeration
from aryx.api.ask_qa.ask_qa_graph_search import _qa_graph_search
from aryx.api.ask_qa.ask_qa_label_collision import _qa_label_collision_response
from aryx.api.ask_qa.ask_qa_multi_attr_options import _qa_multi_attr_options_response
from aryx.api.ask_qa.ask_qa_resume_prompt import _build_qa_resume_prompt
from aryx.api.ask_qa.ask_qa_status_shortcircuit import _qa_status_shortcircuit


def _handle_cpq_qa(
    req: "Any",
    session: Any,
    attrs: list,
    reader: Any,
    resume_review: bool = False,
    product_hint: str = "",
) -> dict[str, Any]:
    """STEP 7 — Contextual Q&A: answer a graph question then resume configuration state.

    Pauses the config loop, queries the graph for context, synthesises an LLM
    answer, then appends the current config resume prompt so the user knows where
    they were. The session state is preserved unchanged.
    """
    _shortcircuit, _meta_result, _meta_it, _meta_ot = _qa_status_shortcircuit(
        req, session, attrs, resume_review,
    )
    if _shortcircuit is not None:
        return _shortcircuit

    _collision_response = _qa_label_collision_response(req, session, attrs)
    if _collision_response is not None:
        return _collision_response

    _multi_attr_response = _qa_multi_attr_options_response(req, session, attrs)
    if _multi_attr_response is not None:
        return _multi_attr_response

    _fast_path_result = _qa_fast_path_or_enumeration(req, session, attrs, product_hint)
    if _fast_path_result is not None:
        qa_answer, (p_in, p_out, p_ms, s_in, s_out, s_ms) = _fast_path_result
    else:
        qa_answer, (p_in, p_out, p_ms, s_in, s_out, s_ms) = _qa_graph_search(
            req, session, attrs, reader, _meta_result, _meta_it, _meta_ot,
        )

    resume = _build_qa_resume_prompt(session, attrs, resume_review)
    answer = qa_answer + resume
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)

    usage = {
        "prompt_tokens": p_in + s_in,
        "completion_tokens": p_out + s_out,
        "latency_ms": p_ms + s_ms,
        "menial_model": "cpq-qa",
        "answer_model": "cpq-qa",
    }
    return {
        "answer": answer,
        "terms": [],
        "tools_called": ["cpq_qa()"],
        "usage": usage,
        "grounding": None,
        "session_data": session.to_dict(),
        "cpq_payload": None,
    }
