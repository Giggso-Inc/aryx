"""Batch mounting-type grid quantities into one ask, allow NLP replies
(ported from dev-rv-msi #305, 2026-09-10, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md's dev-rv-msi transition branch).

A grid selector's per-option quantities (Shirt Magnetic Mount, Jacket
Magnetic Mount, Locking Molle Mount, ...) are queued together by
CpqEngine.resolve_pending_grid_quantities, but the default response-
formatting flow's one-question-per-turn presentation only ever showed
the first one -- forcing a customer through one single-attribute
question per option across many separate turns for what is really one
grid the customer thinks of as a single unit (live-confirmed 2026-09-01:
six sequential turns for one mounting-type grid's six quantity columns).

`_grid_batch_pending_answer` (used by ask_step11_build_response.py's
turn-cap branch and ask_step11_on_request_response.py's default FORMAT-A
branch) combines all of one grid's pending quantities into a single
question. `_try_apply_grid_quantities_batch_reply` (used by
ask_step9_lock_pending_answer.py) is the reply-side counterpart: accepts
the customer's answer in either shape -- an ordered positional list
("7, 8, 1, 3, 9, 4") or free-form named pairs ("Shirt Magnetic Mount is
three, Jacket Magnetic Mount as dozen, Locking Molle Mount= 9") -- via
CpqEngine.parse_grid_batch_quantities. Unmentioned candidates are left
pending rather than defaulted to 0, matching this codebase's never-guess
discipline throughout.

Known limitation, deliberately deferred (same as the original dev-rv-msi
commit): exact label matching only -- shorthand/dropped-qualifier names
(e.g. "Molle Mount" for the full "Locking Molle Mount") don't resolve.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.raven_log import raven_log


def _pending_are_one_grid_batch(pending_vns, attrs: list) -> bool:
    """True when `pending_vns` (2+) are ALL grid-linked quantity
    companions (aryx.cpq.grid_quantity.is_grid_quantity_attr) of the SAME
    array-grid selector -- e.g. a mounting-type grid's per-option
    quantities (Shirt Magnetic Mount, Jacket Magnetic Mount, Locking
    Molle Mount, ...). Shared by both the ask-side batching
    (_grid_batch_pending_answer) and the reply-side batch parsing
    (_try_apply_grid_quantities_batch_reply) so the two stay in sync --
    what gets asked together is exactly what a batched reply is parsed
    against."""
    from aryx.api import ask_api as _ask_api_module

    pending_vns = set(pending_vns)
    if len(pending_vns) < 2:
        return False
    links = _ask_api_module._cpq_engine.resolve_array_grid_links(attrs)
    return any(pending_vns <= set(item_map.values()) for item_map in links.values())


def _grid_batch_pending_answer(
    pending: list, visible_attrs: list, filled: dict, display_filled: dict,
    hiding_rules: list, rec_rules: list,
    constrained_opts: dict, validation_rules: Any, dropped_note: str,
) -> str | None:
    """When every currently-pending attribute is one grid's own quantity
    companions (_pending_are_one_grid_batch) -- resolve_pending_grid_
    quantities already queues every one of them into `pending` at once,
    but the response-formatting flow's default one-question-per-turn
    presentation still only shows pending[0], forcing the customer
    through one single-attribute question per mount type across many
    separate turns for what is really one grid the customer thinks of as
    a single unit -- live-confirmed 2026-09-01: six sequential "Please
    provide a value" turns for one mounting-type grid's six quantity
    columns.

    Returns the combined-question answer text when this condition holds,
    or None to let the caller fall through to its normal one-at-a-time
    formatting. Callers check this ahead of BOTH the session.turn >=
    MAX_TURNS branch and the default (no explicit mode_request) branch,
    so a customer never has to know to ask for "batch" just to answer
    one grid's own quantities together -- an EXPLICIT mode_request
    ("json" or "batch") still takes priority over this at both call
    sites, this only replaces the *default* one-at-a-time presentation.

    2026-09-02 (ported from dev-rv-msi #306, live feedback): a single
    compact bullet list of labels, not a full next_question_prompt block
    (context sentence + "Please provide a value.") stacked per mount --
    unreadable at 5 items, all redundant since every attr shares the
    same grid context. Bullets over a numbered list (Andie Drama-mode
    comparison, dev-rv-msi): no numbering to misalign against a
    positional reply. Also tells the customer HOW they can reply -- a
    positional list in order, OR naming just the ones they need with a
    quantity each (colon/is/as/equals all recognized -- see
    aryx.cpq.grid_quantity.parse_grid_batch_quantities, which
    _try_apply_grid_quantities_batch_reply calls against exactly this
    same pending set on the next turn). Advertising a reply shape this
    function doesn't actually make work would be worse than not
    mentioning it at all.
    """
    if not _pending_are_one_grid_batch(
        {a.variable_name for a in pending}, visible_attrs,
    ):
        return None
    # 2026-09-02 (dev-rv-msi #307 follow-up): joined with "\n\n", not "\n" --
    # a single newline between bullets gets collapsed by the client's
    # markdown renderer, which needs a blank line to separate list items.
    bullets = "\n\n".join(f"  • {a.display_label}" for a in pending)
    example_label = pending[0].display_label
    positional_example = ", ".join(str(n) for n in range(len(pending), 0, -1))
    return (
        (f"{dropped_note.strip()}\n\n" if dropped_note else "")
        + f"These {len(pending)} mount quantities go together:\n\n"
        + bullets
        + "\n\nReply with a quantity for each, e.g.:\n"
        + f'"{positional_example}" (in this order) or "{example_label}: 3"'
    )


def _try_apply_grid_quantities_batch_reply(
    question: str, session: Any, attrs: list,
) -> set[str]:
    """Reply-side counterpart to _grid_batch_pending_answer: when
    session.pending_variables are ALL one grid's own quantity companions
    (_pending_are_one_grid_batch), tries parsing `question` as a batched
    reply covering several of them at once
    (aryx.cpq.grid_quantity.parse_grid_batch_quantities) BEFORE the
    normal single-attribute STEP 5 answer-locking runs.

    On any resolution (partial or complete), writes each resolved value
    straight into session.filled/display_filled/filled_source (same
    fields STEP 5's single-attr path would have written) and removes
    those variable_names from session.pending_variables, then returns
    the set of resolved variable_names -- callers use a non-empty return
    to skip STEP 5's single-attr resolution ENTIRELY for this turn
    (rather than also trying to match `question` against whichever
    variable now happens to be at pending_variables[0]): the reply has
    already been fully accounted for here, once as a batch, and must not
    also be interpreted as a single free-text answer to something it
    was never a reply to. Returns an empty set (no session mutation) if
    the pending set isn't one grid's siblings, or if
    parse_grid_batch_quantities resolves nothing -- the caller then
    proceeds with STEP 5's pre-existing single-attr handling, completely
    unchanged.
    """
    from aryx.api import ask_api as _ask_api_module

    _cpq_engine = _ask_api_module._cpq_engine
    pending_vns = list(session.pending_variables)
    if not _pending_are_one_grid_batch(pending_vns, attrs):
        return set()
    by_vn = {a.variable_name: a for a in attrs}
    candidates = [
        (vn, by_vn[vn].display_label) for vn in pending_vns if vn in by_vn
    ]
    resolved = _cpq_engine.parse_grid_batch_quantities(candidates, question)
    raven_log("DEBUG", "P4", "ask.grid_batch.reply batched quantity reply parsed", context={
        "selected_option": "apply_batch" if resolved else "single_attr_fallback",
        "available_options": ["apply_batch", "single_attr_fallback"],
        "reason_code": (
            "NOTHING_RESOLVED" if not resolved
            else "ALL_RESOLVED" if len(resolved) >= len(candidates) else "PARTIAL_RESOLVED"),
        "candidate_count": len(candidates), "resolved_count": len(resolved or {}),
        "resolved_fields": list(resolved or {})[:25],
        "reply_len": len(question or ""), "turn": getattr(session, "turn", None)})
    if not resolved:
        return set()
    for vn, qty in resolved.items():
        session.filled[vn] = str(qty)
        session.display_filled[vn] = str(qty)
        session.filled_source[vn] = "user"
    session.pending_variables = [
        vn for vn in session.pending_variables if vn not in resolved
    ]
    return set(resolved)


def _grid_batch_count_mismatch_message(
    req: "Any", session: Any, attrs: list,
) -> dict[str, Any] | None:
    """When _try_apply_grid_quantities_batch_reply resolved nothing,
    checks whether that's because the customer gave a purely positional
    reply with the WRONG NUMBER of values
    (aryx.cpq.grid_quantity.grid_batch_count_mismatch) rather than an
    unrelated message. Gives a specific "you gave N, I need M" re-ask
    instead of letting the caller fall through to STEP 5's single-attr
    handling, which would otherwise reject the whole comma-separated
    string against just pending_variables[0] with no explanation of
    what actually went wrong.

    Returns None (caller proceeds with its normal single-attr handling
    unchanged) unless one of two positional-reply shapes is detected: a
    wrong segment count (grid_batch_count_mismatch), or the right count
    with one unparseable segment (grid_batch_unparseable_segment --
    dev-rv-msi PR #307 review follow-up, N1: previously fell through to
    the same generic single-attr rejection this function exists to
    avoid). Returns a full turn-response dict (matching every other
    STEP 5 early-response builder's shape, e.g.
    ask_step9_miss_response.py) ready for the caller to return directly.
    """
    from aryx.api import ask_api as _ask_api_module

    _cpq_engine = _ask_api_module._cpq_engine
    pending_vns = list(session.pending_variables)
    if not _pending_are_one_grid_batch(pending_vns, attrs):
        return None
    by_vn = {a.variable_name: a for a in attrs}
    candidates = [
        (vn, by_vn[vn].display_label) for vn in pending_vns if vn in by_vn
    ]
    given = _cpq_engine.grid_batch_count_mismatch(candidates, req.question)
    if given is not None:
        answer = (
            f"You gave {given} value(s), but there are {len(candidates)} "
            f"mount quantities pending. Reply with one quantity per line or "
            f"comma, in order, for all {len(candidates)}, or name just the "
            f'ones you mean (e.g. "{candidates[0][1]}: 3").'
        )
    else:
        bad_label = _cpq_engine.grid_batch_unparseable_segment(candidates, req.question)
        if bad_label is None:
            raven_log("DEBUG", "P4", "ask.grid_batch.mismatch no positional reply problem", context={
                "selected_option": "single_attr_fallback",
                "available_options": ["count_mismatch_reask", "unparseable_reask", "single_attr_fallback"],
                "reason_code": "NOT_POSITIONAL_PROBLEM", "candidate_count": len(candidates),
                "reply_len": len(getattr(req, "question", None) or ""),
                "turn": getattr(session, "turn", None)})
            return None
        answer = (
            f"I couldn't read one of those quantities — the value for "
            f'"{bad_label}" isn\'t a number I recognize. Reply with a '
            f"quantity for each, in the same order, or name just the "
            f'ones you mean (e.g. "{candidates[0][1]}: 3").'
        )
    raven_log("DEBUG", "P4", "ask.grid_batch.mismatch positional reply re-ask", context={
        "selected_option": "count_mismatch_reask" if given is not None else "unparseable_reask",
        "available_options": ["count_mismatch_reask", "unparseable_reask", "single_attr_fallback"],
        "reason_code": "WRONG_VALUE_COUNT" if given is not None else "UNPARSEABLE_SEGMENT",
        "given_count": given, "candidate_count": len(candidates),
        "reply_len": len(getattr(req, "question", None) or ""),
        "turn": getattr(session, "turn", None)})
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": ["cpq_grid_batch_count_mismatch()"],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "cpq-engine", "answer_model": "cpq-engine"},
        "grounding": None, "session_data": session.to_dict(), "cpq_payload": None,
    }
