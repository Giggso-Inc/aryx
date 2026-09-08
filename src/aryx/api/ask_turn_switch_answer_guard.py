"""Deciding whether a message on an already-anchored session is an
ANSWER to the currently-pending attribute rather than a product-switch
mention, split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to
keep the sibling `ask_turn_switch_redetect.py` under the line cap. Logic
unchanged from the original inline block. `_cpq_engine` is read through
the ask_api MODULE object (not imported by name) since at least one
test replaces the whole singleton via
`patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _is_answer_to_pending_over_switch(
    req: "Any", session: Any, reader: Any, attrs: list, hints: dict,
) -> "tuple[bool, dict[str, str] | None, str | None]":
    """ANSWER-OVER-SWITCH PRECEDENCE (Issue 6, docs/CPQ_PRODUCT_SWITCH_
    ISSUE.md): a message that validly answers the currently-pending
    attribute is an ANSWER, never a switch signal — confirmed live:
    answering the pending Product menu with "APX 6500" scored 0.67
    against the alias "APX™ N70" and was hijacked into a "did you mean
    aSTRO25_bom?" prompt instead of locking. This check needs the
    pending attr's OPTIONS, which is why detection now runs after Step 2
    loads attrs. Options-backed matches only — the free-text tier of
    apply_answer is deliberately not consulted, since it would classify
    ANY text as an answer while a free-text attr is pending, swallowing
    every switch mention.

    productSelectionProduct_all's option list is shared, catalog-wide
    (the exact same ~325 SKU codes on every ingested catalog) — confirmed
    live: a genuine switch sentence legitimately option-matched against
    THIS unrelated catalog's copy of that same list, so is_answer_to_
    pending was True and the switch mention never got checked at all.
    For this one attr specifically, always check switch-detection FIRST
    and only trust the option-match if no other ingested product was
    named — every other pending attr's option list is catalog-specific,
    so the original answer-over-switch precedence stays unchanged for
    them. An exact, standalone match against one of THIS attr's own
    options (the whole reply, not a substring within a longer sentence)
    is a strong "definitely answering" signal regardless of what else
    the text might also resemble — confirmed live: "APX NEXT Single
    Band" is a real SL3500e-catalog option whose own text happens to
    contain a different family's alias ("APX NEXT"), and must still lock
    as an answer. Only a longer sentence that merely CONTAINS an option
    string is ambiguous enough to need the switch-mention probe.

    Returns (is_answer_to_pending, alias_map, switch_candidate) —
    alias_map/switch_candidate are non-None only when the
    productSelectionProduct_all cross-check ran, so the caller can reuse
    them instead of re-fetching (review finding P2).
    """
    _cpq_engine = _ask_api_module._cpq_engine
    pending_attr_guard = next(
        (a for a in attrs
         if session.pending_variables
         and a.variable_name == session.pending_variables[0]),
        None,
    )
    is_answer_to_pending = bool(
        pending_attr_guard is not None
        and pending_attr_guard.options
        and _cpq_engine.apply_answer(pending_attr_guard, req.question)
    )
    _reply_norm = req.question.strip().lower()
    is_exact_option_reply = bool(
        pending_attr_guard is not None
        and any(
            _reply_norm in (o.item_value.strip().lower(), o.display_name.strip().lower())
            for o in (pending_attr_guard.options or ())
        )
    )
    alias_map: dict[str, str] | None = None
    switch_candidate: str | None = None
    if (
        is_answer_to_pending
        and not is_exact_option_reply
        and pending_attr_guard is not None
        and pending_attr_guard.variable_name == "productSelectionProduct_all"
    ):
        alias_map = _cpq_engine.ingested_product_alias_map(reader, req.workspace_id)
        switch_candidate = _cpq_engine.detect_product_mention(
            req.question, hints, reader, req.workspace_id,
            alias_map=alias_map,
        )
        if (
            switch_candidate
            and switch_candidate.strip().lower() != session.product_name.strip().lower()
        ):
            is_answer_to_pending = False
    return is_answer_to_pending, alias_map, switch_candidate
