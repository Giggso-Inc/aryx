"""STEP 6 (activation) handler — re-activating a real, currently-excluded
optional catalog attribute back into the quote, split out of `api/
ask_api.py` (Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definition; the rule-loop recompute lives in the sibling `ask_attr_
activation_recompute.py` purely to keep this file under the line cap.
`_cpq_engine`, `_persist_cpq_history`, `_label_collision_for`,
`_label_collision_prompt`, and `_remember_attr_scope` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path, and this
avoids depending on their definition order relative to this import.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_attr_activation_recompute import _recompute_after_attr_activation
from aryx.api.ask_cpq_summary_text import _cpq_summary_text
from aryx.api.ask_stale_constraint_reask import _reask_stale_constraint_violations


def _handle_attr_activation(
    req: "Any",
    session: Any,
    attrs: list,
    activated_attr: Any,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
) -> dict[str, Any]:
    """STEP 6 (activation) — re-activate a real, currently-excluded,
    optional catalog attribute back into the quote (D2,
    docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md).

    Re-runs the rule loop once, same as every other change/removal
    handler (re-activating an attr can itself affect other rules, e.g. a
    constraint that was only ever evaluated against attrs visible before
    this one existed). `auto_fill`'s existing blind first-by-order
    fallback would happily guess a value for this attr the same way it
    does for any other ordinary optional attr — but the user just
    explicitly asked for THIS one, so it deserves a real question, not a
    guess (D2 §4.3 "never silently guesses"). A genuine rule-derived fill
    (filled_source == "rule"/"country_derived") is a determined value,
    not a guess, and is left alone.
    """
    _cpq_engine = _ask_api_module._cpq_engine
    activated_vn = activated_attr.variable_name

    (
        pending, visible_attrs, filled, display_filled, constrained_opts,
        rule_ids, bml_eval, catalog_prefix,
    ) = _recompute_after_attr_activation(
        req, session, attrs, activated_vn, hiding_rules, rec_rules, con_rules,
    )

    # Built AFTER the override decision inside the recompute helper — a
    # real determined value (e.g. a source="default"/"rule" fill this
    # same pass) gets stated directly rather than a misleading "what
    # value would you like?" when nothing further is actually being asked.
    _activated_label = _cpq_engine.disambiguated_label(activated_attr, attrs)
    if activated_vn in filled:
        _act_display = display_filled.get(activated_vn, filled[activated_vn])
        cascade_note = (
            f"Added **{_activated_label}** → **{_act_display}**."
        )
    else:
        cascade_note = (
            f"Added **{_activated_label}** to your quote — "
            f"what value would you like?"
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
        "answer": answer, "terms": [], "tools_called": ["cpq_attr_activation()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
