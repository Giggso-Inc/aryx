"""Explicit on-request presentation (JSON preview or the full batch of
pending questions) and STEP 4 FORMAT A (context sentence + numbered
options), split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`mode_request` was detected early (before STEP 5) so an explicit request
never gets rejected as an invalid menu answer. The JSON preview payload
is recomputed against the CURRENT `filled` (post-cascade), not the
turn-start hidden set, since cascades earlier in this same turn can
change which hiding rules are active. PROMPT 7: FORMAT A remembers the
exact option list shown so a typo on the next turn re-asks within this
scope (never the full catalog). Logic unchanged from the original
inline block. Every ask_api name below is read through the module
object (not imported by name) since tests patch several of them by
dotted path.
"""

from __future__ import annotations

import json
from typing import Any

from aryx.api import ask_api as _ask_api_module


def _step11_on_request_response(
    req: "Any", session: Any, attrs: list, visible_attrs: list, filled: dict,
    display_filled: dict, pending: list, constrained_opts: dict, rule_ids: set,
    hiding_rules: list, rec_rules: list, con_rules: list, validation_rules: list,
    bml_eval: Any, catalog_prefix: str, mode_request: str | None, dropped_note: str,
) -> str:
    _cpq_engine = _ask_api_module._cpq_engine
    if mode_request == "json":
        _hidden_now = _cpq_engine.apply_hiding_rules(
            attrs, filled, hiding_rules, bml_eval, filled_multi=session.filled_multi)[2]
        _hidden_now = _hidden_now | _cpq_engine.payload_flow_exclusions(
            req.workspace_id, catalog_prefix, attrs)
        preview_payload = _cpq_engine.build_payload(
            filled, session.filled_source, session.filled_multi, visible_attrs,
            hidden_vns=_hidden_now,
            rules=[*hiding_rules, *rec_rules, *con_rules],
            display_order=_cpq_engine.load_layout_display_order(req.workspace_id, catalog_prefix),
            product_quantity=session.product_quantity,
            scope_required_and_edited=True,
            workspace_id=req.workspace_id, catalog_prefix=catalog_prefix)
        summary = _ask_api_module._cpq_summary_text(
            display_filled, attrs, rule_ids,
            session.product_name, req.workspace_id, sources=session.filled_source,
            product_quantity=session.product_quantity, filled=session.filled,
        )
        still_need = ", ".join(a.display_label for a in pending)
        return (
            (f"{dropped_note.strip()}\n\n" if dropped_note else "")
            + (f"{summary}\n\n" if summary else "")
            + f"Here's the configuration so far — **preview, not final**:\n\n"
            f"```json\n{json.dumps(preview_payload, indent=2)}\n```\n\n"
            f"Still need: {still_need}."
        )
    if mode_request == "batch":
        blocks = []
        for a in pending:
            ctx = _cpq_engine.build_context_sentence(
                a, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
            )
            blocks.append(_cpq_engine.next_question_prompt(
                a, ctx, constrained_opts.get(a.entity_id),
                validation_rules=validation_rules, attrs=visible_attrs))
        return (
            (f"{dropped_note.strip()}\n\n" if dropped_note else "")
            + f"Here's everything still needed ({len(pending)} item(s)):\n\n"
            + "\n\n---\n\n".join(blocks)
        )

    # ── STEP 4: FORMAT A — context sentence + numbered options only ──
    next_attr = pending[0]
    _pending_collision = _ask_api_module._label_collision_for(next_attr, visible_attrs, session, pending)
    if _pending_collision:
        session.pending_label_collision_vns = [a.variable_name for a in _pending_collision]
        return dropped_note + _ask_api_module._label_collision_prompt(
            _pending_collision, session, req.question, req.workspace_id)
    context_sentence = dropped_note + _cpq_engine.build_context_sentence(
        next_attr, visible_attrs, filled, display_filled, hiding_rules, rec_rules,
    )
    constrained_vals = constrained_opts.get(next_attr.entity_id)
    answer = _cpq_engine.next_question_prompt(
        next_attr, context_sentence, constrained_vals,
        validation_rules=validation_rules, attrs=visible_attrs,
        already_selected=session.filled_multi.get(next_attr.variable_name),
    )
    _ask_api_module._remember_attr_scope(
        session, next_attr, constrained_vals, req.question,
    )
    return answer
