"""Building the final multi-target cascade response — next-question /
grid-gap / stale-reask / complete-summary branches, split out of
`_handle_cascade_multi` (Phase 4/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling
`ask_handle_cascade_multi.py` under the line cap. Logic unchanged from
the original inline block. `_cpq_engine`, `_persist_cpq_history`,
`_label_collision_for`, `_label_collision_prompt`, and `_remember_attr_
scope` are read through the ask_api MODULE object (not imported by
name) since ask_api tests patch several of its own module-level names
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_cpq_summary_text import _cpq_summary_text
from aryx.api.ask_pending_exclusion import _hard_exclude_from_pending
from aryx.api.ask_singleton_pending import _auto_resolve_singleton_pending
from aryx.api.ask_stale_constraint_reask import _reask_stale_constraint_violations


def _build_cascade_multi_response(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, cascade_note: str, visible_attrs: list, filled: dict,
    display_filled: dict, constrained_opts: dict, pending: list, rule_ids: set,
    bml_eval: Any, catalog_prefix: str,
) -> dict[str, Any]:
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
        session.status = "configuring"
        next_attr = pending[0]
        _pending_collision = _ask_api_module._label_collision_for(
            next_attr, visible_attrs, session, pending,
        )
        if _pending_collision:
            session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
            q_block = _ask_api_module._label_collision_prompt(
                _pending_collision, session, req.question, req.workspace_id)
        else:
            ctx = _cpq_engine.build_context_sentence(
                next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp, attrs=visible_attrs,
                already_selected=session.filled_multi.get(next_attr.variable_name),
            )
            _ask_api_module._remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    elif unresolved_grid_gaps:
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

    _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_cascade_multi()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
