"""``count_turn_intents`` -- read-only diagnostic counting how many
distinct intents a single message contains (Phase 4 step 2 extraction
from ``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Fans out to sibling turn_intent detectors; takes a leading ``engine``
argument purely to forward to ``detect_change_request``/
``detect_change_requests_multi``, which need it (see
``change_request.py``'s module docstring) -- this function does
nothing with it directly.
"""

from __future__ import annotations

import logging

from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.attr_query import detect_attr_query
from aryx.cpq.turn_intent.change_request import (
    detect_change_request,
    detect_change_requests_multi,
    detect_change_target_without_value,
)
from aryx.cpq.turn_intent.collision import detect_change_request_collision
from aryx.cpq.turn_intent.response_state import detect_qa_question, detect_response_mode_request

logger = logging.getLogger(__name__)


def count_turn_intents(
    engine,
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    filled_multi: dict[str, list[str]] | None = None,
) -> list[str]:
    """Read-only diagnostic (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 4,
    incremental step): runs every existing intent detector against one
    message and returns a plain-string label for each one that fired,
    WITHOUT changing what the turn actually does with the result —
    purely observational, logged by the caller.

    Confirmed live this session: "change solution type and primary
    service type" only ever got ONE of its two targets addressed,
    because `detect_change_request_collision` (and every other
    detector in the real turn-processing flow) stops at its own first
    match and the caller returns immediately. This counts how many
    DISTINCT intents a single message actually contains, so that gap
    can be measured against real traffic before any routing behavior
    changes — reuses every detector as-is, adds no new detection
    logic, and never influences the response.
    """
    hits: list[str] = []
    try:
        if detect_qa_question(question, None, strict=True):
            hits.append("qa_question")
    except Exception:  # noqa: BLE001 — diagnostic only, must never break the turn
        logger.debug("count_turn_intents: detect_qa_question failed", exc_info=True)
    try:
        mode = detect_response_mode_request(question)
        if mode:
            hits.append(f"mode_request:{mode}")
    except Exception:  # noqa: BLE001
        logger.debug("count_turn_intents: detect_response_mode_request failed", exc_info=True)
    try:
        collision = detect_change_request_collision(question, attrs, filled, filled_multi)
        if collision:
            hits.append(f"change_collision:{collision[0].display_label}")
    except Exception:  # noqa: BLE001
        logger.debug("count_turn_intents: detect_change_request_collision failed", exc_info=True)
    try:
        multi = detect_change_requests_multi(engine, question, attrs, filled, filled_multi)
        for attr, _hint in multi:
            hits.append(f"change:{attr.variable_name}")
    except Exception:  # noqa: BLE001
        logger.debug("count_turn_intents: detect_change_requests_multi failed", exc_info=True)
    if not any(h.startswith("change:") for h in hits):
        try:
            single = detect_change_request(engine, question, attrs, filled, filled_multi)
            if single:
                hits.append(f"change:{single[0].variable_name}")
        except Exception:  # noqa: BLE001
            logger.debug("count_turn_intents: detect_change_request failed", exc_info=True)
    try:
        no_value = detect_change_target_without_value(question, attrs, filled)
        if no_value:
            hits.append(f"change_no_value:{no_value.variable_name}")
    except Exception:  # noqa: BLE001
        logger.debug("count_turn_intents: detect_change_target_without_value failed", exc_info=True)
    try:
        attr_q = detect_attr_query(question, attrs)
        if attr_q:
            hits.append(f"attr_query:{attr_q.variable_name}")
    except Exception:  # noqa: BLE001
        logger.debug("count_turn_intents: detect_attr_query failed", exc_info=True)
    return hits
