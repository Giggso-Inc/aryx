"""Mid-turn product-switch re-detection for an already-anchored session,
split out of `_run_cpq_turn_inner` (Phase 10/11-phase ask_api
decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Product
already anchored on an earlier turn — re-check THIS turn's text for a
mention of a DIFFERENT product. detect_product_mention is dynamic
(matches against whatever catalogs are actually ingested in this
workspace, not a hardcoded list) and fuzzy — the confirm gate is the
safety net regardless. Logic unchanged from the original inline `if`
block; the answer-vs-switch guard and the prompt-building tail live in
sibling `ask_turn_switch_*.py` files purely to keep this file under the
line cap.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_turn_switch_answer_guard import _is_answer_to_pending_over_switch
from aryx.api.ask_turn_switch_redetect_prompt import _build_switch_redetect_prompt


def _check_mid_turn_switch_redetection(
    req: "Any", session: Any, reader: Any, attrs: list, hints: dict,
) -> dict[str, Any] | None:
    """Returns a response dict when this turn's reply was consumed by a
    switch-confirmation or ambiguous-switch prompt; None when the
    message is an answer to the pending attribute, or no switch
    candidate was found at all, in which case the caller continues with
    the rest of the turn unchanged.
    """
    is_answer_to_pending, alias_map, switch_candidate = _is_answer_to_pending_over_switch(
        req, session, reader, attrs, hints,
    )
    if is_answer_to_pending:
        return None
    return _build_switch_redetect_prompt(req, session, reader, hints, alias_map, switch_candidate)
