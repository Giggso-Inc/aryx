"""STEP 6 (nullify) handler — clearing an optional single-select
attribute's current value back to empty, split out of `api/ask_api.py`
(Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline
definition; the rule-loop recompute lives in the sibling `ask_attr_
clear_recompute.py` purely to keep this file under the line cap.
`_cpq_engine`, `_persist_cpq_history`, `_label_collision_for`,
`_label_collision_prompt`, and `_remember_attr_scope` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path, and this
avoids depending on their definition order relative to this import.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_scope_and_pending.ask_change_decline_and_scope_memory import _remember_attr_scope
from aryx.api.ask_label_collision.ask_label_collision_detect_and_compose import _label_collision_for
from aryx.api.ask_label_collision.ask_label_collision_prompt_and_narrow import _label_collision_prompt
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_attr_recompute.ask_attr_clear_recompute import _recompute_after_attr_clear
from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text
from aryx.api.ask_stale_constraint.ask_stale_constraint_reask import _reask_stale_constraint_violations


def _handle_attr_clear(
    req: "Any",
    session: Any,
    attrs: list,
    cleared_attr: Any,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (nullify) — clear an optional single-select attribute's
    current value back to empty (D4, docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md).

    Sets the value to the empty-string "user"-sourced marker `auto_fill`'s
    single-select branch now respects (mirrors `filled_multi`'s existing
    empty-plus-"user" "(none)" convention) — never immediately re-guessed
    by the blind first-by-order fallback on the rule-loop pass this same
    handler triggers. `detect_attr_clear` already verified live that no
    active rule would refire for this attr before this handler is ever
    called.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    vn = cleared_attr.variable_name
    prev_display = session.display_filled.get(vn, session.filled.get(vn, ""))
    session.filled[vn] = ""
    session.display_filled[vn] = "(none)"
    session.filled_source[vn] = "user"
    cascade_note = (
        f"Cleared **{_cpq_engine.disambiguated_label(cleared_attr, attrs)}** "
        f"(was **{prev_display}**)."
    )

    (
        pending, visible_attrs, filled, display_filled, constrained_opts,
        rule_ids, bml_eval, catalog_prefix,
    ) = _recompute_after_attr_clear(req, session, attrs, hiding_rules, rec_rules, con_rules)

    if pending:
        session.status = "configuring"
        next_attr = pending[0]
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
            _cvals_nqp = constrained_opts.get(next_attr.entity_id)
            q_block = _cpq_engine.next_question_prompt(
                next_attr, ctx, _cvals_nqp, attrs=visible_attrs,
                already_selected=session.filled_multi.get(next_attr.variable_name),
            )
            _remember_attr_scope(session, next_attr, _cvals_nqp, req.question)
        answer = cascade_note + "\n\n" + q_block
    else:
        _stale_reask = _reask_stale_constraint_violations(
            session, attrs, con_rules, bml_eval, req.workspace_id, catalog_prefix,
        )
        if _stale_reask is not None:
            answer = cascade_note + "\n\n" + _stale_reask
        else:
            session.status = "post_approval"
            summary = _cpq_summary_text(
                display_filled, attrs, rule_ids,
                session.product_name, req.workspace_id, sources=session.filled_source,
                product_quantity=session.product_quantity, filled=session.filled,
                product_anchor_hint=session.product_anchor_question,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_attr_clear()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
