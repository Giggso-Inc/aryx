"""Detecting and answering a shared-display-label attribute collision in
a Q&A question, split out of `_handle_cpq_qa` (Phase 8/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to
keep the sibling `ask_handle_cpq_qa.py` under the line cap. Logic
unchanged from the original inline block. `_cpq_engine`, `_persist_cpq_
history`, and `_narrow_label_collision` are read through the ask_api
MODULE object (not imported by name) since ask_api tests patch several
of its own module-level names by dotted path, and `_narrow_label_
collision` is not yet split out of ask_api.py.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _qa_label_collision_response(
    req: "Any", session: Any, attrs: list,
) -> dict[str, Any] | None:
    """Label collision check first — a shared display_label across 2+
    distinct attrs (real BigMachines source-data reuse, docs/CPQ_
    SESSION_2_OPEN_ISSUES.md item 2) must be disambiguated, never
    silently resolved to whichever attr happens to be first in list
    order. Returns None when there is no collision, in which case the
    caller proceeds to the next Q&A stage unchanged.
    """
    _collision = _ask_api_module._cpq_engine.detect_label_collision(req.question, attrs)
    if not _collision:
        return None
    _collision = _ask_api_module._narrow_label_collision(req.question, _collision)
    _lines = "\n".join(
        f"- **{a.variable_name}**"
        f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
        for a in _collision
    )
    qa_answer = (
        f"There are {len(_collision)} different attributes labeled "
        f"**\"{_collision[0].display_label}\"** in this catalog — which one "
        f"did you mean?\n\n{_lines}"
    )
    # Remembered so the NEXT turn's reply (a bare variable_name, a list
    # index, or looser phrasing an LLM fallback resolves — see
    # _run_cpq_turn's resolution block) answers THIS prompt instead of
    # being read as an unrelated message (live-verified gap,
    # 2026-07-23 — same class of bug already fixed for the
    # change-request collision via pending_change_collision_vns).
    session.pending_label_collision_vns = [a.variable_name for a in _collision]
    session.pending_label_collision_question = req.question
    _ask_api_module._persist_cpq_history(req.workspace_id, req.question, qa_answer)
    return {
        "answer": qa_answer, "terms": [], "tools_called": ["cpq_label_collision()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
