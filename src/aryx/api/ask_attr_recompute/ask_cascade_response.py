"""Building the final STEP-6 cascade response — next-question / grid-gap
/ stale-reask / complete-summary branches, split out of `_handle_cascade`
(Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md) purely to keep the sibling `ask_handle_cascade.py`
under the line cap. Logic unchanged from the original inline block.
`_cpq_engine`, `_persist_cpq_history`, `_label_collision_for`, `_label_
collision_prompt`, `_remember_attr_scope`, and `_queue_followup_note`
are read through the ask_api MODULE object (not imported by name) since
ask_api tests patch several of its own module-level names by dotted
path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_change_decline_and_scope_memory import _remember_attr_scope
from aryx.api.ask_intent_queue_text_helpers import _queue_followup_note
from aryx.api.ask_label_collision.ask_label_collision_detect_and_compose import _label_collision_for
from aryx.api.ask_label_collision.ask_label_collision_prompt_and_narrow import _label_collision_prompt
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text
from aryx.api.ask_pending_exclusion import _hard_exclude_from_pending
from aryx.api.ask_singleton_pending import _auto_resolve_singleton_pending
from aryx.api.ask_stale_constraint.ask_stale_constraint_reask import _reask_stale_constraint_violations


def _build_cascade_response(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, cascade_note: str, visible_attrs: list, filled: dict,
    display_filled: dict, constrained_opts: dict, pending: list, rule_ids: set,
    bml_eval: Any, catalog_prefix: str,
) -> dict[str, Any]:
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    unresolved_grid_gaps = _cpq_engine.unresolved_grid_quantity_options(
        visible_attrs, session.filled_multi)
    pending = _hard_exclude_from_pending(
        pending, filled, display_filled, session.filled_source,
        con_rules, bml_eval, rec_rules=rec_rules,
        workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
        all_attrs=attrs,
    )
    pending = _auto_resolve_singleton_pending(
        pending, filled, display_filled, session.filled_source,
        con_rules, bml_eval, workspace_id=req.workspace_id, catalog_prefix=catalog_prefix,
    )
    if pending:
        # New conflicts to resolve → FORMAT A (change notice + next question only)
        session.status = "configuring"
        next_attr = pending[0]
        # Queue head that is already filled still needs a value pick — set
        # pending_change_no_value so the next bare reply is captured as the
        # new value (same as _build_no_value_response).
        if (
            session.pending_intent_queue
            and next_attr.variable_name == session.pending_intent_queue[0]
            and session.filled.get(next_attr.variable_name)
        ):
            session.pending_change_no_value_vn = next_attr.variable_name
        _pending_collision = _label_collision_for(
            next_attr, visible_attrs, session, pending,
        )
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals, attrs=visible_attrs,
                already_selected=session.filled_multi.get(next_attr.variable_name),
            )
            _remember_attr_scope(session, next_attr, _cvals, req.question)
        answer = cascade_note + "\n\n" + q_block
        answer += _queue_followup_note(session, attrs)
    elif unresolved_grid_gaps:
        # A selected grid option has NO resolvable quantity attr at all
        # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 9) — never silently
        # complete with a permanent per-row gap; block and ask the
        # customer to resolve it (remove the selection or pick another).
        session.status = "configuring"
        gap_list = "; ".join(f"**{val}** ({label})" for label, val in unresolved_grid_gaps)
        answer = (
            cascade_note + "\n\n"
            f"⚠️ {gap_list} has no quantity field configured in this "
            f"catalog. Please remove it or choose a different option "
            f"before this configuration can be completed."
        )
    else:
        _stale_reask = _reask_stale_constraint_violations(
            session, attrs, con_rules, bml_eval, req.workspace_id, catalog_prefix,
        )
        if _stale_reask is not None:
            answer = cascade_note + "\n\n" + _stale_reask
        else:
            # All resolved → verbose summary, JSON only on request (§6/Phase K)
            session.status = "awaiting_approval"
            summary = _cpq_summary_text(
                display_filled, attrs, rule_ids,
                session.product_name, req.workspace_id, sources=session.filled_source,
                product_quantity=session.product_quantity, filled=session.filled,
            )
            answer = (
                cascade_note + "\n\n"
                f"Configuration complete for **{session.product_name}**.\n\n"
                + (f"{summary}\n\n" if summary else "")
                + f"Click **JSON** below to see the full payload, "
                  f"say **confirm** to submit, or describe any changes."
            )

    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_cascade()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
