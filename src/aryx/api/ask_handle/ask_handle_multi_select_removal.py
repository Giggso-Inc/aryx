"""STEP 6 (removal) handler — deselecting one or more options from an
already-selected multi-select, split out of `api/ask_api.py` (Phase 4/
11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Logic unchanged from the original inline definition; the
rule-loop recompute lives in the sibling `ask_multi_select_removal_
recompute.py` purely to keep this file under the line cap. `_cpq_engine`,
`_persist_cpq_history`, `_label_collision_for`, `_label_collision_prompt`,
and `_remember_attr_scope` are read through the ask_api MODULE object
(not imported by name) since ask_api tests patch several of its own
module-level names by dotted path, and this avoids depending on their
definition order relative to this import.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_change_decline_and_scope_memory import _remember_attr_scope
from aryx.api.ask_label_collision_detect_and_compose import _label_collision_for
from aryx.api.ask_label_collision_prompt_and_narrow import _label_collision_prompt
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_response_building.ask_cpq_summary_text import _cpq_summary_text
from aryx.api.ask_attr_recompute.ask_multi_select_removal_qty_drop import _drop_related_quantity_attrs
from aryx.api.ask_attr_recompute.ask_multi_select_removal_recompute import (
    _recompute_after_multi_select_removal,
)
from aryx.api.ask_stale_constraint.ask_stale_constraint_reask import _reask_stale_constraint_violations


def _handle_multi_select_removal(
    req: "Any",
    session: Any,
    attrs: list,
    changed_attr: Any,
    to_remove: list[str],
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (removal) — deselect one or more options from an already-
    selected multi-select (e.g. "remove Jacket Magnetic Mount" after both
    Shirt and Jacket were selected).

    Also drops the removed option's own per-option quantity attr (via
    resolve_array_grid_links) — a quantity for a mount no longer selected
    is stale data, not a value worth keeping around or re-showing.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    current = session.filled_multi.get(changed_attr.variable_name, [])
    remaining = [v for v in current if v not in to_remove]
    removed_display = [
        next((o.display_name for o in changed_attr.options if o.item_value == v), v)
        for v in to_remove
    ]
    session.filled_multi[changed_attr.variable_name] = remaining
    if remaining:
        session.display_filled[changed_attr.variable_name] = ", ".join(
            next((o.display_name for o in changed_attr.options if o.item_value == v), v)
            for v in remaining
        )
    else:
        # An empty selection after an explicit removal is a settled,
        # user-confirmed answer (same "(none)" convention auto_fill's own
        # decline-handling uses) — never silently re-guessed or re-asked.
        session.display_filled[changed_attr.variable_name] = "(none)"
    session.filled_source[changed_attr.variable_name] = "user"

    dropped_qty_labels = _drop_related_quantity_attrs(
        session, attrs, changed_attr, to_remove,
    )

    cascade_note = (
        f"Removed **{', '.join(removed_display)}** from "
        f"**{_cpq_engine.disambiguated_label(changed_attr, attrs)}** "
        f"— now: **{session.display_filled[changed_attr.variable_name]}**."
    )
    if dropped_qty_labels:
        cascade_note += (
            f" Also cleared {', '.join(f'**{lbl}**' for lbl in dropped_qty_labels)} "
            f"— no longer needed."
        )

    # Re-run the rule loop once, same as the single-change cascade path —
    # a removal can un-invalidate a constraint or re-open an option the
    # prior selection had closed off.
    (
        pending, visible_attrs, filled, display_filled, constrained_opts,
        rule_ids, bml_eval, catalog_prefix, unresolved_grid_gaps,
    ) = _recompute_after_multi_select_removal(
        req, session, attrs, hiding_rules, rec_rules, con_rules,
    )
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

    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_multi_select_removal()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
