"""Persisting grounded pending-clarify state and returning the clarify
response, split out of `api/ask_api.py` (Phase 2/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic
unchanged from the original inline definition. `_cpq_engine`,
`_persist_cpq_history`, `_build_no_value_response`, and
`_with_classify_usage` are read through the ask_api MODULE object (not
imported by name) since ask_api tests patch several of its own
module-level names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_build_no_value_response import _build_no_value_response
from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_pending_clarify_apply import (
    _apply_pending_clarify_resolution,
    _clear_pending_clarify,
)
from aryx.api.ask_pending_clarify_grounding import _ground_clarify_candidates
from aryx.api.ask_pending_clarify_match import _reply_matches_attr_option
from aryx.api.ask_pending_clarify_prompt import _grounded_clarify_prompt
from aryx.cpq.session_guard import (
    guided_mode_offer_message,
    note_clarify,
    should_force_numbered_options,
    should_offer_guided_mode,
)


def _set_pending_clarify_and_answer(
    req: "Any",
    session: Any,
    attrs: list,
    original_question: str,
    clarifying_question: str | None,
    con_rules: list | None = None,
    bml_eval: Any = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    tool_name: str = "cpq_intent_gateway_clarify()",
    hidden_vns: set[str] | None = None,
    hiding_rules: list | None = None,
    rec_rules: list | None = None,
) -> dict[str, Any]:
    """Persist grounded clarify state and return the clarify response."""
    from aryx.api import ask_api as _ask_api_module
    candidates = _ground_clarify_candidates(
        original_question, attrs, session, clarifying_question, hidden_vns=hidden_vns,
    )
    # docs/config_consistency_issues_2026-07-30.md issue 4 — a fresh clarify
    # can re-propose an attribute the customer already resolved earlier in
    # this session (e.g. "Frequency Bands"), and the triggering utterance
    # can be a bare value ("VHF") that's ALSO legal on other candidates
    # (Frequency Band/Msl, Primary/Secondary Frequency) — genuinely
    # ambiguous on its own, confirmed live. If the remembered anchor is
    # among these candidates and the utterance is one of ITS real option
    # values, resolve straight to it instead of re-asking a question
    # already answered. Requires rule context (con_rules) to actually
    # apply the change; without it there's nothing to replay against yet.
    _anchor_vn = session.last_clarified_attr_vn
    if (
        _anchor_vn
        and con_rules is not None
        and hiding_rules is not None
        and rec_rules is not None
    ):
        _anchor_attr = next(
            (a for a in candidates if a.variable_name == _anchor_vn), None,
        )
        if _anchor_attr is not None and _reply_matches_attr_option(
            original_question, _anchor_attr,
        ):
            return _apply_pending_clarify_resolution(
                req, session, attrs, _anchor_vn, original_question,
                hiding_rules, rec_rules, con_rules, bml_eval,
            )
    # Single grounded candidate → skip the extra question; ask for value.
    #
    # docs/CPQ_AMBIGUOUS_CLARIFY_DISCARDS_RESOLVED_EVIDENCE_PLAN_2026_08_21.md
    # -- a fix attempted here (auto-applying an already-stated value via
    # _apply_pending_clarify_resolution, which re-runs detect_change_
    # request) was reverted: this branch is reached specifically when the
    # gateway called the turn AMBIGUOUS or the deterministic detector
    # disagreed with it (see test_cpq_llm_verdict_checkpoint_2026_08_13.py's
    # "blanket LLM-as-final-verdict" checkpoint) -- re-running the same
    # deterministic match here would silently dispatch a mutating change
    # the gateway had just explicitly declined to trust, exactly the
    # failure mode that checkpoint exists to block (live-confirmed:
    # test_change_request_rejected_by_gateway_never_executes started
    # failing with this change in place). Left as a known, still-open gap
    # for the SmartProgramming-shaped case -- needs a narrower fix that
    # can distinguish "reached here via genuine multi-attribute word-
    # overlap ambiguity" from "reached here via mutating_disagreement"
    # before it's safe to auto-apply anything.
    if len(candidates) == 1 and con_rules is not None:
        _clear_pending_clarify(session)
        return _with_classify_usage(
            _build_no_value_response(
                req, session, attrs, candidates[0], con_rules, bml_eval,
                f"{tool_name}->single_candidate",
            ),
            prompt_tokens, completion_tokens,
        )

    if len(candidates) >= 2:
        session.pending_clarify_vns = [a.variable_name for a in candidates]
        session.pending_clarify_question = original_question
        session.pending_clarify_prompt = _grounded_clarify_prompt(candidates, attrs)
        session.pending_clarify_asked_turn = int(session.turn or 0)
        session.pending_clarify_misses = 0
        answer = session.pending_clarify_prompt
    elif len(candidates) == 1:
        # No rule context yet — stash as no-value pending for next turn.
        _clear_pending_clarify(session)
        session.pending_change_no_value_vn = candidates[0].variable_name
        answer = (
            f"Which value would you like for "
            f"**{_ask_api_module._cpq_engine.disambiguated_label(candidates[0], attrs)}**?"
        )
    else:
        # No catalog-grounded candidates — still ask, but without binding
        # memory to invented names.
        _clear_pending_clarify(session)
        answer = (
            clarifying_question
            or "Which field and value should I use? Please name the attribute."
        )

    _vn_key = candidates[0].variable_name if candidates else None
    note_clarify(session, _vn_key or "_pending_clarify")
    if should_force_numbered_options(session, _vn_key or "_pending_clarify") and candidates:
        answer = _grounded_clarify_prompt(candidates, attrs)
        session.pending_clarify_prompt = answer
    if should_offer_guided_mode(session):
        answer = f"{answer}\n\n{guided_mode_offer_message()}"
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return _with_classify_usage({
        "answer": answer, "terms": list(session.pending_clarify_vns),
        "tools_called": [tool_name],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }, prompt_tokens, completion_tokens)
