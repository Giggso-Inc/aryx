"""STEP 6 (cascade) handler — applying a change, invalidating
dependents, and re-running the rule loop, split out of `api/ask_api.py`
(Phase 4/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md). Logic unchanged from the original inline
definition; every stage lives in a sibling `ask_cascade_*.py` file purely
to keep this file under the line cap. `_cpq_engine`, `_persist_cpq_
history`, `_is_decline_reply`, `_label_collision_for`, `_label_collision_
prompt`, `_remember_attr_scope`, and `_queue_followup_note` are read
through the ask_api MODULE object (not imported by name) since ask_api
tests patch several of its own module-level names by dotted path, and
this avoids depending on their definition order relative to this import.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_label_collision.ask_decline_reply_and_label_collision_llm import _is_decline_reply
from aryx.api.ask_label_collision.ask_label_collision_detect_and_compose import _DECLINE_CHANGE_RE
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_attr_recompute.ask_cascade_apply_value import _apply_cascade_new_value
from aryx.api.ask_attr_recompute.ask_cascade_invalidate_dependents import _invalidate_cascade_dependents
from aryx.api.ask_attr_recompute.ask_cascade_note import _build_cascade_note
from aryx.api.ask_attr_recompute.ask_cascade_recompute import _recompute_after_cascade
from aryx.api.ask_attr_recompute.ask_cascade_response import _build_cascade_response


def _handle_cascade(
    req: "Any",
    session: Any,
    attrs: list,
    changed_attr: Any,
    new_value_hint: str,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
    constrained_item_values: list[str] | None = None,
) -> dict[str, Any]:
    """STEP 6 — Cascade: apply a change, invalidate dependents, re-run rule loop."""
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _cascade_label = _cpq_engine.disambiguated_label(changed_attr, attrs)
    if _is_decline_reply(
        new_value_hint, _cascade_label,
        session.display_filled.get(changed_attr.variable_name, ""),
        req.workspace_id,
        deterministic_hit=bool(_DECLINE_CHANGE_RE.search(new_value_hint)),
    ):
        # Customer declined the pending change (docs/CPQ_SESSION_2026_07_29_
        # ISSUES_PLAN.md #2, LLM fallback added per docs/CPQ_REGEX_VS_LLM_
        # ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row 15-16) — keep the
        # current value, don't touch session.filled/pop/cascade at all,
        # and don't attempt apply_answer against a phrase that was never
        # meant as a value.
        current_display = session.display_filled.get(changed_attr.variable_name, "")
        label = _cascade_label
        answer = (
            f"No changes made — **{label}** stays as "
            f"**{current_display}**." if current_display else
            f"No changes made to **{label}**."
        )
        session.status = "configuring" if session.pending_variables else session.status
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_decline_change()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    hints, negated_vns, catalog_prefix, dependent_labels, hc_allowed = (
        _invalidate_cascade_dependents(
            req, session, attrs, changed_attr, hiding_rules, rec_rules, con_rules,
        )
    )
    result, apply_constrained = _apply_cascade_new_value(
        session, changed_attr, new_value_hint, hc_allowed,
    )
    if not result:
        # Could not parse new value — ask for clarification, using the SAME
        # constrained scope just used to validate the answer (the fix for
        # #3/#10 — these two calls must never diverge; also excludes the
        # rejected option, same as the apply attempt above).
        opts_prompt = _cpq_engine.next_question_prompt(
            changed_attr, constrained_item_values=apply_constrained, attrs=attrs,
        )
        answer = (
            f"I couldn't match that to a valid option for "
            f"**{_cpq_engine.disambiguated_label(changed_attr, attrs)}**. "
            f"Please choose one:\n\n{opts_prompt}"
        )
        session.pending_variables = [changed_attr.variable_name] + [
            v for v in session.pending_variables if v != changed_attr.variable_name
        ]
        session.status = "configuring"
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_cascade()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    (
        visible_attrs, filled, display_filled, constrained_opts, pending,
        rule_ids, bml_eval, dropped_multi, user_value_overridden, requested_display,
    ) = _recompute_after_cascade(
        req, session, attrs, changed_attr, result, hints, negated_vns, catalog_prefix,
        hiding_rules, rec_rules, con_rules,
    )

    cascade_note = _build_cascade_note(
        session, attrs, changed_attr, new_value_hint, dependent_labels,
        dropped_multi, user_value_overridden, requested_display,
    )

    return _build_cascade_response(
        req, session, attrs, hiding_rules, rec_rules, con_rules, cascade_note,
        visible_attrs, filled, display_filled, constrained_opts, pending,
        rule_ids, bml_eval, catalog_prefix,
    )
