"""STEP 5 deterministic pending-answer matching, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Tries the user's full
utterance first (they may have typed the exact option name), only
falling back to the extracted hint if the full question produces no
match — hints are coarse and can mis-match when multiple options share
the same keyword. A grid-quantity attr's question only ever accepts a
digit or a decline; parse_grid_quantity_reply is the sole authority on
that — a miss must stay a miss, never fall back to apply_answer's own
free-text tier accepting arbitrary text as a number. Logic unchanged
from the original inline block. `_cpq_engine` and `logger` are read
through the ask_api module object (not imported by name) since tests
patch several ask_api names by dotted path.
"""

from __future__ import annotations

from typing import Any

from aryx.api import ask_api as _ask_api_module


def _step9_match_pending_answer(
    req: "Any", session: Any, attrs: list, pending_attr: Any, pending_constrained: list | None,
    hint_val_for_attr: str | None, scope_match_text: str,
) -> "tuple[Any, list]":
    """Returns (result, multi_matches). `result` is `(item_value,
    display_name)` or None; `multi_matches` is the list of every
    `(item_value, display_name)` pair a multi-select answer named (empty
    for a single-select attr).
    """
    _cpq_engine = _ask_api_module._cpq_engine
    logger = _ask_api_module.logger

    multi_matches: list = []
    if pending_attr.select_type == "multi":
        # A multi-select answer can name several options at once — scan
        # for every option mentioned instead of the single best match.
        multi_matches = _cpq_engine.apply_multi_answer(
            pending_attr, req.question, pending_constrained)
        if not multi_matches and hint_val_for_attr:
            multi_matches = _cpq_engine.apply_multi_answer(
                pending_attr, hint_val_for_attr, pending_constrained)
        result = multi_matches[0] if multi_matches else None
    else:
        _is_gq_attr = (
            not pending_attr.options
            and _cpq_engine.is_grid_quantity_attr(pending_attr, attrs)
        )
        _gq_reply = (
            _cpq_engine.parse_grid_quantity_reply(req.question)
            if _is_gq_attr else None
        )
        if _is_gq_attr:
            result = (_gq_reply, _gq_reply) if _gq_reply is not None else None
        else:
            result = _cpq_engine.apply_answer(
                pending_attr, scope_match_text, pending_constrained)
            if not result and scope_match_text != req.question:
                result = _cpq_engine.apply_answer(
                    pending_attr, req.question, pending_constrained)
            if not result and hint_val_for_attr:
                result = _cpq_engine.apply_answer(
                    pending_attr, hint_val_for_attr, pending_constrained)
        if not result:
            logger.info(
                "cpq_apply_answer_miss attr=%s reply=%r hint=%r "
                "n_options=%d run_id=%s",
                pending_attr.variable_name, req.question,
                hint_val_for_attr, len(pending_attr.options or []),
                session.run_id or "-",
            )
    return result, multi_matches
