"""STEP 7 strict Q&A during active configuration, and pending
SYSTEM-INITIATED next-question collision resolution — split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). The collision check is
checked here, before STEP 5's normal pending-answer handling, else this
reply is misread as an (invalid) answer to the WRONG, still-first-in-
order colliding attr (live-verified regression fix, 2026-07-26) — a
prior turn's own "what do we ask next" step (_label_collision_for) found
the engine's auto-picked pending[0] label-collided with another attr and
asked which one was meant, instead of silently guessing. Same resolution
shape as the pre-existing Q&A/change-request collision paths:
deterministic first (exact variable_name or 1-based index), LLM fallback
only for looser phrasing. Logic unchanged from the original inline
block. Every ask_api name below is read through the module object (not
imported by name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_label_collision import ask_decline_reply_and_label_collision_llm as _ask_decline_reply_and_label_collision_llm_module
from aryx.api.ask_handle import ask_handle_cpq_qa as _ask_handle_cpq_qa_module


def _step8_qa_and_pending_collision(
    req: "Any", session: Any, attrs: list, reader: Any, hiding_rules: list,
    rec_rules: list, con_rules: list, bml_eval: Any, catalog_prefix: str,
    mode_request: str | None,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was answered by the strict
    Q&A check or resolved a pending system-initiated collision; None
    otherwise, in which case the caller continues.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    logger.info("cpq_step: step7_qa_gate enter run_id=%s", session.run_id)
    # `and not mode_request`: an explicit JSON/batch request must win here
    # too, same as it does over Step 5 below — otherwise a batch request
    # starting with "what" (e.g. "what else do you need from me") is
    # misread as a Q&A question instead of the batch-listing request it
    # actually is.
    if session.pending_variables and session.turn > 1 and not mode_request:
        pending_var_for_qa = session.pending_variables[0]
        pending_attr_for_qa = next(
            (a for a in attrs if a.variable_name == pending_var_for_qa), None,
        )
        if _cpq_engine.detect_qa_question(req.question, pending_attr_for_qa, strict=True):
            return _ask_handle_cpq_qa_module._handle_cpq_qa(req, session, attrs, reader, resume_review=False)

    if session.pending_label_collision_vns and not session.pending_label_collision_question:
        _pqc_reply = req.question.strip()
        _pqc_resolved_vn = None
        if _pqc_reply in session.pending_label_collision_vns:
            _pqc_resolved_vn = _pqc_reply
        elif _pqc_reply.isdigit():
            _pqc_idx = int(_pqc_reply) - 1
            if 0 <= _pqc_idx < len(session.pending_label_collision_vns):
                _pqc_resolved_vn = session.pending_label_collision_vns[_pqc_idx]
        if _pqc_resolved_vn is None:
            _pqc_candidates = [
                a for a in attrs if a.variable_name in session.pending_label_collision_vns
            ]
            if _pqc_candidates:
                _pqc_resolved_vn = _ask_decline_reply_and_label_collision_llm_module._llm_resolve_label_collision(
                    _pqc_reply, _pqc_candidates, session, req.workspace_id)
        if _pqc_resolved_vn:
            return _resolve_pending_question_collision(
                req, session, attrs, _pqc_resolved_vn, hiding_rules, rec_rules,
                con_rules, bml_eval, catalog_prefix,
            )
        # Unrecognized reply — clear stale state rather than getting
        # stuck forever asking the same disambiguation prompt.
        session.pending_label_collision_vns = []
    return None


def _resolve_pending_question_collision(
    req: "Any", session: Any, attrs: list, pqc_resolved_vn: str, hiding_rules: list,
    rec_rules: list, con_rules: list, bml_eval: Any, catalog_prefix: str,
) -> dict[str, Any] | None:
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _pqc_resolved_attr = next(
        (a for a in attrs if a.variable_name == pqc_resolved_vn), None)
    session.pending_label_collision_vns = []
    if _pqc_resolved_attr is None:
        return None
    session.pending_variables = [_pqc_resolved_attr.variable_name] + [
        v for v in session.pending_variables if v != _pqc_resolved_attr.variable_name
    ]
    _pqc_constrained_opts = _cpq_engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval,
        filled_multi=session.filled_multi,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
        narrowing_rec_rules=rec_rules,
    )
    _pqc_grid_pending = _cpq_engine.append_pending_grid_quantities(
        [_pqc_resolved_attr], attrs, session.filled, session.filled_multi,
        session.filled_source, _pqc_constrained_opts,
    )
    if (
        _pqc_grid_pending
        and _pqc_grid_pending[0].variable_name != _pqc_resolved_attr.variable_name
    ):
        _pqc_resolved_attr = _pqc_grid_pending[0]
        _pqc_grid_vns = [a.variable_name for a in _pqc_grid_pending]
        session.pending_variables = _pqc_grid_vns + [
            v for v in session.pending_variables if v not in _pqc_grid_vns
        ]
    _pqc_ctx = _cpq_engine.build_context_sentence(
        _pqc_resolved_attr, attrs, session.filled, session.display_filled,
        hiding_rules, rec_rules,
    )
    _pqc_constrained = _pqc_constrained_opts.get(_pqc_resolved_attr.entity_id)
    _pqc_q_block = _cpq_engine.next_question_prompt(
        _pqc_resolved_attr, _pqc_ctx, _pqc_constrained, attrs=attrs,
    )
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _pqc_q_block)
    return {
        "answer": _pqc_q_block, "terms": [],
        "tools_called": ["cpq_pending_question_collision_resolved()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
