"""STEP 6 (bulk quantity) handler — setting every already-selected grid
row's quantity attr to the same value in one turn, split out of `api/
ask_api.py` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definition; the rule-loop recompute lives in the sibling `ask_bulk_
quantity_recompute.py` purely to keep this file under the line cap.
`_cpq_engine`, `_persist_cpq_history`, `_label_collision_for`,
`_label_collision_prompt`, and `_remember_attr_scope` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path, and this
avoids depending on their definition order relative to this import.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_bulk_quantity_recompute import _recompute_after_bulk_quantity_change
from aryx.api.ask_cpq_summary_text import _cpq_summary_text
from aryx.api.ask_stale_constraint_reask import _reask_stale_constraint_violations


def _handle_bulk_quantity_change(
    req: "Any",
    session: Any,
    attrs: list,
    selector_vn: str,
    item_values: list[str],
    new_qty: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (bulk quantity) — set every already-selected row's quantity
    attr for one grid selector to the same value in one turn (e.g. "change
    both the mounting types quantity to 67").
    """
    _cpq_engine = _ask_api_module._cpq_engine
    grid_links = _cpq_engine.resolve_array_grid_links(attrs)
    item_map = grid_links.get(selector_vn, {})
    by_vn = {a.variable_name: a for a in attrs}
    selector_attr = by_vn.get(selector_vn)
    updated_labels: list[str] = []
    _seen_qty_vns: set[str] = set()
    for item_value in item_values:
        qty_vn = item_map.get(item_value.strip().lower())
        # resolve_array_grid_links' substring heuristic can map two
        # distinct options (e.g. "MOLLE Mount" and "Locking Molle Mount")
        # to the SAME quantity attr — set it once, not once per option, so
        # the cascade note doesn't list the same attr twice.
        if not qty_vn or qty_vn in _seen_qty_vns:
            continue
        _seen_qty_vns.add(qty_vn)
        qty_attr = by_vn.get(qty_vn)
        session.filled[qty_vn] = new_qty
        session.display_filled[qty_vn] = new_qty
        session.filled_source[qty_vn] = "user"
        updated_labels.append(qty_attr.display_label if qty_attr else qty_vn)

    selector_label = selector_attr.display_label if selector_attr else selector_vn
    cascade_note = (
        f"Set {', '.join(f'**{lbl}**' for lbl in updated_labels)} to **{new_qty}**."
        if updated_labels else
        f"Couldn't find a quantity field for the selected **{selector_label}** options."
    )

    (
        pending, visible_attrs, filled, display_filled, constrained_opts,
        rule_ids, bml_eval, catalog_prefix, unresolved_grid_gaps,
    ) = _recompute_after_bulk_quantity_change(
        req, session, attrs, hiding_rules, rec_rules, con_rules,
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
        "answer": answer, "terms": [], "tools_called": ["cpq_bulk_quantity_change()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
