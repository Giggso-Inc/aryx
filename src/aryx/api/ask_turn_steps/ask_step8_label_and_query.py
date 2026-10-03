"""Label-collision detection, attribute option query, and free-text
constraint query for the currently-pending attr — the first three gates
of the pre-STEP-5 preamble, split out of `_run_cpq_turn_inner` (Phase
10/11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). Shared display_label across 2+ distinct attrs must be
disambiguated, never silently resolved (docs/CPQ_SESSION_2_OPEN_
ISSUES.md item 2) — checked before the options-query fast path. The
free-text constraint query (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
Amendment 20 follow-up) only answers when a ValidationRule's script
matches a describable idiom; never guesses. Logic unchanged from the
original inline block. Every ask_api name below is read through the
module object (not imported by name) since tests patch several of them
by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _build_attr_query_response
from aryx.api.ask_label_collision.ask_label_collision_prompt_and_narrow import _narrow_label_collision
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.raven_log import raven_log


def _step8_label_collision_and_query(
    req: "Any", session: Any, attrs: list, validation_rules: list, con_rules: list,
    bml_eval: Any, mode_request: str | None,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn was a label collision, an
    attribute option query, or a free-text constraint query about the
    pending attr; None otherwise, in which case the caller continues.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine

    _collision = _cpq_engine.detect_label_collision(req.question, attrs)
    if _collision:
        _collision_raw_count = len(_collision)
        _collision = _narrow_label_collision(req.question, _collision)
        raven_log("DEBUG", "P4", "ask.collision.label user label collision asked", context={
            "selected_option": "label_collision",
            "available_options": ["label_collision", "attr_query", "free_text_constraint", "continue"],
            "reason_code": "SHARED_DISPLAY_LABEL", "detected_count": _collision_raw_count,
            "narrowed_count": len(_collision or []),
            "candidate_fields": [getattr(a, "variable_name", None) for a in (_collision or [])][:25],
            "question_len": len(getattr(req, "question", None) or ""),
            "turn": getattr(session, "turn", None)})
        _lines = "\n".join(
            f"- **{a.variable_name}**"
            f"{f' (currently: {session.display_filled.get(a.variable_name)})' if session.display_filled.get(a.variable_name) else ''}"
            for a in _collision
        )
        answer = (
            f"There are {len(_collision)} different attributes labeled "
            f"**\"{_collision[0].display_label}\"** in this catalog — which one "
            f"did you mean?\n\n{_lines}"
        )
        _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_label_collision()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    queried_attr = _cpq_engine.detect_attr_query(req.question, attrs)
    if queried_attr:
        raven_log("DEBUG", "P4", "ask.qa.attr_query attribute option query answered", context={
            "selected_option": "attr_query",
            "available_options": ["label_collision", "attr_query", "free_text_constraint", "continue"],
            "reason_code": "ATTR_OPTION_QUERY",
            "queried_field": getattr(queried_attr, "variable_name", None),
            "question_len": len(getattr(req, "question", None) or ""),
            "turn": getattr(session, "turn", None)})
        return _build_attr_query_response(
            req, session, attrs, con_rules, bml_eval, queried_attr,
        )

    if (
        session.pending_variables and not mode_request
        and any(kw in req.question.lower() for kw in _cpq_engine._OPTIONS_KEYWORDS)
    ):
        _pending_attr_for_constraint = next(
            (a for a in attrs if a.variable_name == session.pending_variables[0]), None,
        )
        if _pending_attr_for_constraint and not _pending_attr_for_constraint.options:
            _constraint_desc = _cpq_engine.describe_free_text_constraint(
                _pending_attr_for_constraint, validation_rules,
            )
            raven_log("DEBUG", "P4", "ask.qa.free_text_constraint pending constraint query checked", context={
                "selected_option": "free_text_constraint" if _constraint_desc else "continue",
                "available_options": ["free_text_constraint", "continue"],
                "reason_code": "CONSTRAINT_DESCRIBED" if _constraint_desc else "NO_DESCRIBABLE_IDIOM",
                "pending_field": getattr(_pending_attr_for_constraint, "variable_name", None),
                "validation_rule_count": len(validation_rules or []),
                "turn": getattr(session, "turn", None)})
            if _constraint_desc:
                answer = (
                    f"**{_cpq_engine.disambiguated_label(_pending_attr_for_constraint, attrs)}** "
                    f"doesn't have a fixed list of values — it's free text, but it must "
                    f"only contain {_constraint_desc}."
                )
                _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
                return {
                    "answer": answer, "terms": [_pending_attr_for_constraint.variable_name],
                    "tools_called": ["cpq_free_text_constraint()"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                              "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
                    "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
                }
    raven_log("DEBUG", "P4", "ask.preamble.label_query no gate matched", context={
        "selected_option": "continue",
        "available_options": ["label_collision", "attr_query", "free_text_constraint", "continue"],
        "reason_code": "NO_COLLISION_OR_QUERY",
        "pending_count": len(getattr(session, "pending_variables", None) or []),
        "mode_request": mode_request, "turn": getattr(session, "turn", None)})
    return None
