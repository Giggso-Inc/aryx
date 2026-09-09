"""STEP 5 pending-answer commit — storing a matched result and
invalidating its cascade dependents, split out of `_run_cpq_turn_inner`
(Phase 10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). A catalog-authored warning-message rule must not be
silently accepted just because the value fragment-matched (Amendment
12). Locking a pending answer can invalidate cascade dependents the
exact same way an explicit "change X to Y" message does — every
dependent gets the same four-dict clear `_handle_cascade` uses,
including the DECISION_REQUIRED_KEYS sibling-fill-forward this session
otherwise only reaches via a fresh cascade. Logic unchanged from the
original inline block. Every ask_api name below is read through the
module object (not imported by name) since tests patch several of them
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.engine import DECISION_REQUIRED_KEYS
from aryx.cpq.pending_scope import clear_pending_scope
from aryx.cpq.session_guard import push_snapshot

from aryx.api.ask_stale_constraint.ask_invalidate_stale_base_model import _invalidate_stale_base_model

from aryx.api import ask_core_helpers as _ask_core_helpers_module


def _step9_apply_pending_result(
    req: "Any", session: Any, attrs: list, pending_attr: Any, pending_var: str,
    result: Any, multi_matches: list, hiding_rules: list, rec_rules: list,
    con_rules: list, validation_rules: list, bml_eval: Any,
) -> dict[str, Any] | None:
    """Stores the matched answer and invalidates its cascade dependents.
    Returns a response dict only when a validation-rule warning rejects
    the value outright; None otherwise (the caller falls through to
    STEP 5b/STEP 3 unchanged, same as the original inline block).
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    clear_pending_scope(session)
    iv, disp = result
    push_snapshot(session, reason="attr_fill")
    if pending_attr.select_type == "multi":
        existing = session.filled_multi.get(pending_var, [])
        for match_iv, _match_disp in multi_matches:
            if match_iv not in existing:
                existing = [*existing, match_iv]
        session.filled_multi[pending_var] = existing
        session.display_filled[pending_var] = ", ".join(
            next((o.display_name for o in pending_attr.options
                  if o.item_value == v), v)
            for v in existing
        )
        session.filled_source[pending_var] = "user"
    else:
        session.filled[pending_var] = iv
        session.display_filled[pending_var] = disp
        session.filled_source[pending_var] = "user"
        _validation_warnings = _cpq_engine.apply_validation_rules(
            attrs, session.filled, validation_rules, bml_eval=bml_eval,
            filled_multi=session.filled_multi)
        _warning_msg = _validation_warnings.get(pending_var)
        if _warning_msg:
            del session.filled[pending_var]
            session.display_filled.pop(pending_var, None)
            session.filled_source.pop(pending_var, None)
            _opts_prompt = _cpq_engine.next_question_prompt(pending_attr, attrs=attrs)
            _validation_answer = f"⚠️ {_warning_msg}\n\n{_opts_prompt}"
            _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, _validation_answer)
            return {
                "answer": _validation_answer, "terms": [],
                "tools_called": ["cpq_validation_warning()"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                          "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
            }
    pv_flat = pending_var.lower().replace("_", "")
    matched_fragment = next(
        (dk for dk in DECISION_REQUIRED_KEYS if dk in pv_flat), None
    )
    if matched_fragment:
        for sibling in attrs:
            svn = sibling.variable_name
            if svn in session.filled or sibling.options:
                continue
            if matched_fragment in svn.lower().replace("_", ""):
                session.filled[svn] = iv
                session.display_filled[svn] = disp
                session.filled_source[svn] = "cascade"
    _pv_dependent_eids = _cpq_engine.find_cascade_dependents(
        pending_attr, attrs, hiding_rules, rec_rules, con_rules,
    )
    _pv_by_eid = {a.entity_id: a for a in attrs}
    for _pv_eid in _pv_dependent_eids:
        _pv_dep = _pv_by_eid.get(_pv_eid)
        if _pv_dep and _pv_dep.variable_name != pending_var:
            session.filled.pop(_pv_dep.variable_name, None)
            session.filled_multi.pop(_pv_dep.variable_name, None)
            session.display_filled.pop(_pv_dep.variable_name, None)
            session.filled_source.pop(_pv_dep.variable_name, None)
    _invalidate_stale_base_model(
        session, pending_attr, _pv_dependent_eids, _pv_by_eid,
    )
    return None
