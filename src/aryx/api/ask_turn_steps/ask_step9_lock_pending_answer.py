"""STEP 5 orchestrator: locking the user's answer to the previously
pending attribute, split out of `_run_cpq_turn_inner` (Phase 10/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
`pending_var` must be bound regardless of whether the inner branch runs
— the STEP 5 convergence block later in the turn (clear_queue_vn)
references it unconditionally; None on a fresh/first-turn message is the
correct, intended value. A message with a change verb naming some OTHER
real attr (never the currently-pending one) is treated as a genuine new
request and skipped here entirely, falling through to the mid-config
change-request gate instead (live-verified gap, 2026-07-28). Each
sub-stage lives in a sibling `ask_step9_*.py` file purely to keep this
orchestrator under the line cap; the final dispatch mirrors the original
inline if/elif priority exactly (matched result -> apply; optional
multi-select decline -> record and fall through; low-confidence LLM pick
-> ask; plain miss -> scoped re-ask). Logic and stage order unchanged
from the original inline block.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.api.ask_turn_steps.ask_grid_batch_quantity import (
    _grid_batch_count_mismatch_message,
    _try_apply_grid_quantities_batch_reply,
)
from aryx.api.ask_turn_steps.ask_step9_apply_result import _step9_apply_pending_result
from aryx.api.ask_turn_steps.ask_step9_decline_multiselect import _step9_decline_optional_multiselect
from aryx.api.ask_turn_steps.ask_step9_llm_fallback_match import _step9_llm_fallback_match
from aryx.api.ask_turn_steps.ask_step9_match_answer import _step9_match_pending_answer
from aryx.api.ask_turn_steps.ask_step9_miss_response import (
    _step9_low_confidence_response,
    _step9_options_miss_response,
)
from aryx.api.ask_turn_steps.ask_step9_scope_setup import _step9_scope_and_constraint_setup

from aryx.api.ask_llm.ask_llm_topic_switch_and_change_decline import _pending_reply_is_topic_switch


def _step9_lock_pending_answer(
    req: "Any", session: Any, attrs: list, hints: dict, hiding_rules: list,
    rec_rules: list, con_rules: list, validation_rules: list, bml_eval: Any,
    catalog_prefix: str, mode_request: str | None,
) -> "tuple[dict[str, Any] | None, str | None]":
    """Returns (early_response, pending_var). `early_response` is
    non-None when this turn was fully answered by the pending-answer
    lock; the caller must return it immediately when present.
    `pending_var` is always returned (None when this gate didn't run at
    all) since later STEP 5 convergence logic references it
    unconditionally.
    """
    pending_var: str | None = None
    if not (session.pending_variables and session.turn > 1 and not mode_request):
        return None, pending_var

    # 2026-09-01 (ported from dev-rv-msi #305): before locking `req.question`
    # as an answer to a single pending attr, check whether it's actually a
    # batched reply covering several grid-sibling quantities at once (the
    # reply-side counterpart to _grid_batch_pending_answer, which asks these
    # siblings together in the first place). A non-empty result already
    # wrote every resolved value into session.filled and pruned
    # session.pending_variables, so this turn's `req.question` must NOT
    # also be tried as a single free-text answer to whatever's left pending
    # — it was never a reply to that; pending_var stays None and the caller
    # proceeds with whatever STEP 5 convergence logic runs next.
    if _try_apply_grid_quantities_batch_reply(req.question, session, attrs):
        return None, pending_var

    # 2026-09-02 (ported from dev-rv-msi #307): a purely positional batch
    # reply with the wrong value count is genuinely ambiguous (see
    # grid_batch_count_mismatch's own docstring — never guessed) but
    # deserves a SPECIFIC re-ask rather than falling through to the
    # single-attr handling below, which would reject the whole
    # comma-separated string against just pending_variables[0] with no
    # explanation of what actually went wrong.
    _mismatch_response = _grid_batch_count_mismatch_message(req, session, attrs)
    if _mismatch_response is not None:
        return _mismatch_response, pending_var

    pending_var = session.pending_variables[0]
    pending_attr = next(
        (a for a in attrs if a.variable_name == pending_var), None,
    )
    _looks_like_new_request = _pending_reply_is_topic_switch(
        req.question, pending_attr, attrs, session.filled,
        session.filled_multi, req.workspace_id,
    )
    if not (pending_attr and not _looks_like_new_request):
        return None, pending_var

    (
        early_response, hint_val_for_attr, pending_constrained, scope_cands,
        scope_for_attr, scope_match_text,
    ) = _step9_scope_and_constraint_setup(
        req, session, attrs, pending_attr, pending_var, hints, con_rules, bml_eval,
        catalog_prefix,
    )
    if early_response is not None:
        return early_response, pending_var

    result, multi_matches = _step9_match_pending_answer(
        req, session, attrs, pending_attr, pending_constrained, hint_val_for_attr,
        scope_match_text,
    )
    result, llm_low_confidence_candidates = _step9_llm_fallback_match(
        req, pending_attr, pending_constrained, scope_for_attr, scope_cands, result,
    )

    if result:
        _resp = _step9_apply_pending_result(
            req, session, attrs, pending_attr, pending_var, result, multi_matches,
            hiding_rules, rec_rules, con_rules, validation_rules, bml_eval,
        )
        if _resp is not None:
            return _resp, pending_var
    elif (pending_attr.select_type == "multi"
            and not pending_attr.required
            and re.match(r"^\s*(no|none|nope|skip|nothing|not\s+needed)\b",
                         req.question.strip().lower())):
        _step9_decline_optional_multiselect(
            session, pending_attr, pending_var, pending_constrained, attrs,
        )
    elif llm_low_confidence_candidates:
        return _step9_low_confidence_response(
            req, session, attrs, pending_attr, pending_var, llm_low_confidence_candidates,
        ), pending_var
    elif pending_attr.options:
        return _step9_options_miss_response(
            req, session, attrs, pending_attr, pending_var, pending_constrained,
        ), pending_var

    return None, pending_var
