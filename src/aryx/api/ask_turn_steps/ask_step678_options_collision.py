"""Pending OPTIONS-QUERY label-collision resolution for the awaiting_
approval/post_approval review status, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). A PRIOR turn's detect_label_collision (inside
_handle_cpq_qa) asked "which one did you mean?" and stored the
candidates + original question; this resolves THAT prompt instead of
letting _handle_cpq_qa treat this turn as a fresh, unrelated question
(live-verified gap, 2026-07-23). Deterministic first (exact variable_name
or 1-based list index); an LLM fallback only for looser phrasing. Logic
unchanged from the original inline block. Every ask_api name below is
read through the module object (not imported by name) since tests patch
several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_label_collision import ask_decline_reply_and_label_collision_llm as _ask_decline_reply_and_label_collision_llm_module
from aryx.api.ask_handle import ask_handle_cpq_qa as _ask_handle_cpq_qa_module


def _resolve_pending_options_collision(
    req: "Any", session: Any, attrs: list, reader: Any, catalog_prefix: str,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn resolved (or was consumed
    by) a pending options-query label collision; None when there was no
    such pending collision, in which case the caller continues.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    if not session.pending_label_collision_vns:
        return None
    _lc_reply = req.question.strip()
    _lc_resolved_vn = None
    if _lc_reply in session.pending_label_collision_vns:
        _lc_resolved_vn = _lc_reply
    elif _lc_reply.isdigit():
        _lc_idx = int(_lc_reply) - 1
        if 0 <= _lc_idx < len(session.pending_label_collision_vns):
            _lc_resolved_vn = session.pending_label_collision_vns[_lc_idx]
    if _lc_resolved_vn is None:
        _lc_candidates = [
            a for a in attrs
            if a.variable_name in session.pending_label_collision_vns
        ]
        if _lc_candidates:
            _lc_resolved_vn = _ask_decline_reply_and_label_collision_llm_module._llm_resolve_label_collision(
                _lc_reply, _lc_candidates, session, req.workspace_id)
    if _lc_resolved_vn:
        _lc_resolved_attr = next(
            (a for a in attrs if a.variable_name == _lc_resolved_vn), None)
        _lc_orig_question = session.pending_label_collision_question
        session.pending_label_collision_vns = []
        session.pending_label_collision_question = ""
        if _lc_resolved_attr is not None and _lc_orig_question:
            _lc_req = req.model_copy(update={"question": _lc_orig_question})
            return _ask_handle_cpq_qa_module._handle_cpq_qa(
                _lc_req, session, [_lc_resolved_attr], reader, resume_review=True)
        if _lc_resolved_attr is not None:
            return _resolve_system_initiated_collision(
                req, session, attrs, _lc_resolved_attr, catalog_prefix,
                hiding_rules, rec_rules, con_rules, bml_eval,
            )
    # Unrecognized reply (deterministic AND LLM fallback both came up
    # empty) — clear the stale pending state and fall through to normal
    # routing rather than getting stuck forever.
    session.pending_label_collision_vns = []
    session.pending_label_collision_question = ""
    return None


def _resolve_system_initiated_collision(
    req: "Any", session: Any, attrs: list, lc_resolved_attr: Any, catalog_prefix: str,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
) -> dict[str, Any]:
    """System-initiated collision (Amendment 4 follow-up,
    _label_collision_for) — no original user question to resume, since
    the engine itself picked pending[0] and found it label-collided, not
    a user's own Q&A query. Just ask the customer's now-disambiguated
    attr next.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    session.pending_variables = [lc_resolved_attr.variable_name] + [
        v for v in session.pending_variables if v != lc_resolved_attr.variable_name
    ]
    _lc_constrained_opts = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval,
        filled_multi=session.filled_multi,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
        narrowing_rec_rules=rec_rules,
    )
    _lc_grid_pending = _cpq_engine.append_pending_grid_quantities(
        [lc_resolved_attr], attrs, session.filled, session.filled_multi,
        session.filled_source, _lc_constrained_opts,
        selector_vns={lc_resolved_attr.variable_name},
    )
    if (
        _lc_grid_pending
        and _lc_grid_pending[0].variable_name != lc_resolved_attr.variable_name
    ):
        lc_resolved_attr = _lc_grid_pending[0]
        _lc_grid_vns = [a.variable_name for a in _lc_grid_pending]
        session.pending_variables = _lc_grid_vns + [
            v for v in session.pending_variables if v not in _lc_grid_vns
        ]
    _lc_ctx = _cpq_engine.build_context_sentence(
        lc_resolved_attr, attrs, session.filled, session.display_filled,
        hiding_rules, rec_rules,
    )
    _lc_constrained = _lc_constrained_opts.get(lc_resolved_attr.entity_id)
    _lc_q_block = _cpq_engine.next_question_prompt(
        lc_resolved_attr, _lc_ctx, _lc_constrained, attrs=attrs,
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _lc_q_block)
    return {
        "answer": _lc_q_block, "terms": [],
        "tools_called": ["cpq_pending_question_collision_resolved()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
