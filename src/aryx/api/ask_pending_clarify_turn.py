"""Top-level pending-clarify turn handler — tries to resolve a reply
against a previously-issued clarify prompt before falling through to
normal dispatch, split out of `api/ask_api.py` (Phase 2/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition. `_cpq_engine`,
`_is_global_change_decline`, and `_persist_cpq_history` are read through
the ask_api MODULE object (not imported by name) since ask_api tests
patch several of its own module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module
from aryx.api.ask_pending_clarify_apply import (
    _apply_pending_clarify_resolution,
    _clear_pending_clarify,
)
from aryx.api.ask_pending_clarify_match import _match_pending_clarify_reply
from aryx.api.ask_pending_clarify_prompt import _grounded_clarify_prompt
from aryx.api.ask_target_description import _resolve_target_description
from aryx.cpq.session_guard import (
    guided_mode_offer_message,
    note_clarify,
    should_force_numbered_options,
    should_offer_guided_mode,
)


def _handle_pending_clarify_turn(
    req: "Any",
    session: Any,
    attrs: list,
    hiding_rules: list,
    rec_rules: list,
    con_rules: list,
    bml_eval: Any,
) -> dict[str, Any] | None:
    """If a gateway clarify is pending, try to resolve this reply first.

    Returns a response dict when the pending path handles the turn;
    None when no pending_clarify is set (caller continues normally).
    """
    if not session.pending_clarify_vns:
        return None

    candidates = [
        a for a in attrs if a.variable_name in session.pending_clarify_vns
    ]
    # Preserve original candidate order from pending_clarify_vns
    order = {vn: i for i, vn in enumerate(session.pending_clarify_vns)}
    candidates.sort(key=lambda a: order.get(a.variable_name, 999))

    if not candidates:
        # Catalog no longer has these attrs — clear and fall through.
        _clear_pending_clarify(session)
        return None

    global_change_decline = _ask_api_module._is_global_change_decline(req.question)
    if global_change_decline:
        clarify_status, resolved_vn = ("decline", None)
    else:
        # docs/config_consistency_issues_2026-07-30.md Issue 11: a stale/wrong
        # candidate pool must never force-match an unrelated, well-formed
        # follow-up request. Resolve fresh named changes against every attr;
        # a target outside the stale pool belongs to normal dispatch.
        if (
            _ask_api_module._cpq_engine._CHANGE_VERB_RE.search(req.question)
            or _ask_api_module._cpq_engine._ARROW_RE.search(req.question)
        ):
            _fresh_attr, _fresh_candidates = _resolve_target_description(
                req.question, attrs,
            )
            if (
                _fresh_attr is not None
                and _fresh_attr.variable_name not in session.pending_clarify_vns
            ):
                _clear_pending_clarify(session)
                return None

        clarify_status, resolved_vn = _match_pending_clarify_reply(
            req.question, candidates, session, req.workspace_id,
        )
    if clarify_status == "resolved" and resolved_vn:
        return _apply_pending_clarify_resolution(
            req, session, attrs, resolved_vn,
            session.pending_clarify_question or req.question,
            hiding_rules, rec_rules, con_rules, bml_eval,
        )

    # Explicit decline (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_
    # ISSUE.md §5.2) — LLM-classified, not regex — never treat "no" as
    # just another failed guess. Clear the stale candidate list (which
    # may itself be wrong, e.g. a compound change+question message the
    # gateway couldn't resolve to one target) and ask a genuinely open
    # question instead of re-showing the same list a third time.
    if clarify_status == "decline":
        _clear_pending_clarify(session)
        answer = (
            "No problem — no attributes were changed."
            if global_change_decline
            else (
                "No problem — could you tell me specifically which attribute "
                "or setting you'd like to change or ask about?"
            )
        )
        _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [],
            "tools_called": ["cpq_pending_clarify_decline()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }

    # Miss — do not mis-bind. Re-prompt; after 2 misses force numbered list.
    session.pending_clarify_misses = int(session.pending_clarify_misses or 0) + 1
    note_clarify(session, "_pending_clarify")
    if session.pending_clarify_misses >= 2 or should_force_numbered_options(
        session, "_pending_clarify",
    ):
        prompt = _grounded_clarify_prompt(candidates, attrs)
        session.pending_clarify_prompt = prompt
    else:
        prompt = (
            session.pending_clarify_prompt
            or _grounded_clarify_prompt(candidates, attrs)
        )
        prompt = (
            f"I still need to know which attribute you meant.\n\n{prompt}"
        )
    if should_offer_guided_mode(session):
        prompt = f"{prompt}\n\n{guided_mode_offer_message()}"
    _ask_api_module._persist_cpq_history(req.workspace_id, req.question, prompt)
    return {
        "answer": prompt, "terms": list(session.pending_clarify_vns),
        "tools_called": ["cpq_pending_clarify_reprompt()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
