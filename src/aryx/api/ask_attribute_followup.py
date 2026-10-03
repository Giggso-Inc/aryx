"""Read a reply as the value for the attribute the bot just asked about.

After "Products offer these Carrier Selection options: …. Which one do you
need?", the session holds `pending_attribute_label` ("carrier selection").
The reply ("ATT", "the verizon one", "2") is matched against the values on
offer with the same in-scope matching used for any "did you mean" list
(digit, exact, partial, fuzzy). A match continues exactly like a first
message that named that value. No match returns None, and run_ask clears
the pending label and routes the reply normally -- the customer may have
moved on ("actually I want APX Next").
"""

from __future__ import annotations

import logging
from typing import Any

from aryx.api.ask_attribute_search import _budget_s, decide
from aryx.api.ask_request_models import AskRequest
from aryx.cpq.attribute_search.budget import run_with_budget
from aryx.cpq.attribute_search.lookup import find_products_by_attribute
from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision
from aryx.cpq.pending_scope.pending_scope import resolve_against_scope
from aryx.cpq.state import CpqSession
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


def _route_attribute_followup(req: AskRequest, reader: Any) -> dict[str, Any] | None:
    """Continue an attribute search from the reply, or None if it isn't a value."""
    from aryx.api import ask_api as _ask_api_module

    session = CpqSession.from_dict(req.session_data)
    label = session.pending_attribute_label
    engine = _ask_api_module._cpq_engine

    def _lookup() -> tuple[Any, Any] | None:
        """(match, result) for the reply, or None when it isn't an offered value."""
        offered = find_products_by_attribute(label, None, workspace_id=req.workspace_id,
                                             reader=reader, engine=engine)
        if offered is None or not offered.offered_values:
            return None
        match = resolve_against_scope(req.question, list(offered.offered_values))
        if not match.matched:
            logger.info("attribute_search: follow-up %r is not a %r value", req.question, label)
            return None
        return match, find_products_by_attribute(label, match.matched, reader=reader,
                                                 workspace_id=req.workspace_id, engine=engine)

    try:
        found = run_with_budget(_lookup, budget_s=_budget_s())
    except Exception as exc:  # noqa: BLE001 -- over budget or failed: route the reply normally
        logger.warning("attribute_search: follow-up lookup failed or over budget", exc_info=True)
        raven_log("WARN", "P3", "ask.attr_search.followup_failed follow-up routed normally",
                  error_code="ARYX_ASK_ATTR_SEARCH_FOLLOWUP_FAILED",
                  context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                           "backoff_ms": 0, "recovery_selected": "route_reply_normally", "fallback_target": None,
                           "exit_condition": "exception", "result": "degraded", "attribute_label": label})
        return None
    if found is None or found[1] is None:
        return None
    match, res = found
    meta = AskRouteDecision(
        route="attribute_search", confidence="high", clarifying_question=None,
        rationale="attribute_search_followup", attribute_label=label,
        attribute_value=match.matched,
        quantity=session.product_quantity if session.product_quantity > 1 else None,
        country=session.country or None,
    )
    return decide(req, reader, meta, res, anchor_question=session.product_anchor_question)


def _attribute_followup_or_forget(
    req: AskRequest, reader: Any,
) -> tuple[dict[str, Any] | None, AskRequest]:
    """run_ask's hook: (response, req) for a reply to a pending "which value?".

    Nothing pending: (None, req) unchanged. A value: (its response, req).
    Not a value: (None, req with the pending attribute cleared).
    """
    if not (req.session_data or {}).get("pending_attribute_label"):
        return None, req
    response = _route_attribute_followup(req, reader)
    if response is not None:
        return response, req
    return None, req.model_copy(update={
        "session_data": {**req.session_data, "pending_attribute_label": ""},
    })
