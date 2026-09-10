"""Answering a compound multi-attribute options question, split out of
`_handle_cpq_qa` (Phase 8/11-phase ask_api decomposition, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling `ask_
handle_cpq_qa.py` under the line cap. Logic unchanged from the original
inline block. `_cpq_engine`, `_persist_cpq_history`, and `_build_attr_
options_text` are read through the ask_api MODULE object (not imported
by name) since ask_api tests patch several of its own module-level
names by dotted path, and `_build_attr_options_text` is not yet split
out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_text_helpers import _build_attr_options_text
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_llm import ask_llm_split_multi_attr_options as _ask_llm_split_multi_attr_options_module


def _qa_multi_attr_options_response(
    req: "Any", session: Any, attrs: list,
) -> dict[str, Any] | None:
    """docs/config_consistency_issues_2026-07-30.md issue 3 — compound
    multi-attribute options query, must run BEFORE the single-attr fast
    path: detect_attr_query only ever returns ONE best match, so "what
    are the Frequency Bands and Wireless Carrier available?" would
    otherwise silently answer just one and drop the other. LLM-first,
    gated behind a cheap options-keyword + conjunction pre-check so the
    common single-attribute case never pays this call. Returns None when
    fewer than 2 of the split questions resolve to a real attribute —
    caller falls through to the single-attr fast path unchanged rather
    than returning a half-answered response.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if not (
        any(kw in req.question.lower() for kw in _cpq_engine._OPTIONS_KEYWORDS)
        and (" and " in f" {req.question.lower()} " or "," in req.question)
    ):
        return None
    _multi_qs = _ask_llm_split_multi_attr_options_module._llm_split_multi_attr_options_query(
        req.question, attrs, req.workspace_id,
    )
    if not _multi_qs:
        return None
    _multi_answers = []
    _multi_qa_vns: list[str] = []
    for _sub_q in _multi_qs:
        _sub_attr = _cpq_engine.detect_attr_query(_sub_q, attrs)
        _sub_answer = (
            _build_attr_options_text(req, session, attrs, _sub_attr)
            if _sub_attr else None
        )
        if _sub_answer:
            _multi_answers.append(_sub_answer)
            _multi_qa_vns.append(_sub_attr.variable_name)
    if len(_multi_answers) < 2:
        return None
    # Remember EVERY attribute this compound query asked about, not just
    # the last one processed — see last_qa_variables' own docstring
    # (Issue 12).
    session.last_qa_variables = _multi_qa_vns
    qa_answer = "\n\n".join(_multi_answers)
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, qa_answer)
    return {
        "answer": qa_answer, "terms": [],
        "tools_called": ["cpq_multi_attr_options()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
