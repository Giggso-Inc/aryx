"""Resolving a pending "which value?" clarifying question left over from
a previous turn's valueless change request, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md — docs/CPQ_MID_CONFIG_
CHANGE_REQUEST_PLAN.md Related finding 1). The reply IS the new value
directly, not a fresh hint, so it must be captured before any other
detection runs, regardless of session.status — same reasoning as the
pending_change_collision_vns/pending_label_collision_vns checks
elsewhere. Logic unchanged from the original inline block. Every
ask_api name below is read through the module object (not imported by
name) since tests patch several of them by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _resolve_pending_change_no_value(
    req: "Any", session: Any, attrs: list, hiding_rules: list, rec_rules: list,
    con_rules: list, bml_eval: Any,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn resolved (or was consumed
    by) a pending change-no-value clarification; None when there was no
    such pending state, in which case the caller continues.
    """
    if not session.pending_change_no_value_vn:
        return None
    logger = _ask_api_module.logger
    _cpq_engine = _ask_api_module._cpq_engine
    _pcnv_attr = next(
        (a for a in attrs if a.variable_name == session.pending_change_no_value_vn), None,
    )
    session.pending_change_no_value_vn = ""
    # Same topic-switch gap as STEP 5's pending-answer lock (docs/
    # CPQ_PENDING_TOPIC_SWITCH_PLAN_2026_08_11.md), but on this earlier,
    # separate "which value?" pending mechanism — confirmed live
    # 2026-08-11: with Hardware Version pending here, "First i wanted to
    # changed Wireless Carrier" has no _CHANGE_VERB_RE match ("changed"
    # isn't "change"/"changing") and named a DIFFERENT real attr in plain
    # language, but this block had no topic-switch check of its own — it
    # forced the whole message into `_handle_cascade` as a literal
    # (failing) new value for Hardware Version, producing "I couldn't
    # match that to a valid option for Hardware Version." Falls through
    # to normal routing (identical to the STEP 5 fix) whenever the LLM
    # confidently identifies a different real target.
    if _pcnv_attr and _ask_api_module._pending_reply_is_topic_switch(
        req.question, _pcnv_attr, attrs, session.filled,
        session.filled_multi, req.workspace_id,
    ):
        _pcnv_attr = None
    if not _pcnv_attr:
        return None
    # QA issue #3: re-derive constrained set for scoped match/retry.
    # §15: try/except so pure declines never crash on rule engine.
    try:
        _pcnv_constrained = _cpq_engine.apply_constraint_rules(
            attrs, con_rules, session.filled, bml_eval, filled_multi=session.filled_multi,
        ).get(_pcnv_attr.entity_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "cpq: constraint recompute failed for pending change "
            "value on %r, proceeding unconstrained: %r",
            _pcnv_attr.variable_name, exc,
        )
        _pcnv_constrained = None
    # PROMPT 6: extract wanted (+ rejected); exclude rejected option.
    _pcnv_wanted, _pcnv_rejected = _ask_api_module._extract_replacement_clause(req.question)
    _pcnv_match_text = _pcnv_wanted or req.question
    _pcnv_constrained = _ask_api_module._constrain_excluding_rejected(
        _pcnv_attr, _pcnv_rejected, _pcnv_constrained,
    )
    # QA issue #2: try real value FIRST; only treat as decline when
    # nothing resolves (compound "don't want Standard; use Premium").
    if _pcnv_attr.select_type == "multi":
        _pcnv_matched = bool(_cpq_engine.apply_multi_answer(
            _pcnv_attr, _pcnv_match_text, _pcnv_constrained,
        ))
    else:
        _pcnv_matched = _cpq_engine.apply_answer(
            _pcnv_attr, _pcnv_match_text, _pcnv_constrained,
        ) is not None
    _pcnv_current = session.display_filled.get(_pcnv_attr.variable_name)
    if not _pcnv_matched and _ask_api_module._is_decline_reply(
        req.question, _cpq_engine.disambiguated_label(_pcnv_attr, attrs),
        _pcnv_current or "", req.workspace_id,
        deterministic_hit=_ask_api_module._is_change_value_decline(req.question),
    ):
        # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row
        # 15-16: LLM fallback added for decline phrasing the
        # deterministic regex doesn't cover.
        answer = (
            f"No problem — I'll leave "
            f"**{_cpq_engine.disambiguated_label(_pcnv_attr, attrs)}** "
            f"as it is"
            + (f" (**{_pcnv_current}**)." if _pcnv_current else ".")
        )
        _ask_api_module._persist_cpq_history(req.workspace_id, req.question, answer)
        return {
            "answer": answer, "terms": [], "tools_called": ["cpq_change_declined()"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                      "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
            "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
        }
    # Multi-intent follow-up (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 4) is
    # now handled INSIDE _handle_cascade itself — it's the single common
    # convergence point every change-request entry point reaches, so
    # re-queuing pending_multi_intent_vn there covers this caller too
    # without needing its own copy here.
    return _ask_api_module._handle_cascade(
        req, session, attrs, _pcnv_attr, _pcnv_match_text,
        hiding_rules, rec_rules, con_rules,
        constrained_item_values=_pcnv_constrained,
    )
