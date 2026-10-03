"""/ask handler for route=attribute_search (attribute-first discovery).

"I want a product that has ATT as a carrier" -> find the product families
whose catalog menu options (or Data Table rows) offer that value, then:

- 1 family: start its quote with the value filled in;
- 2..N families (ARYX_CPQ_ATTR_SEARCH_MAX_CHOICES, default 5): offer them;
- more than N: ask which product family;
- no value given ("Which products are available for carrier selection"):
  list the values on offer and read the reply as the value;
- only Data Table models, or nothing: answer with the list.

See ask_attribute_handoff.py for those steps. Returns None -- so run_ask
takes the normal quote path -- when the message names a product (the
product wins), when the attribute can't be grounded, or when the lookup
fails. `_cpq_engine` is read through the ask_api MODULE object, same
convention as ask_feature_region_search.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aryx.api import ask_attribute_handoff as _handoff
from aryx.api.ask_attribute_search_answers import _format_answer
from aryx.api.ask_request_models import AskRequest
from aryx.config import get_settings
from aryx.cpq.attribute_search.budget import BudgetExceeded, run_with_budget
from aryx.cpq.attribute_search.lookup import AttributeSearchResult, find_products_by_attribute
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CHOICES = 5
_DEFAULT_BUDGET_S = 25.0


def _max_choices() -> int:
    """ARYX_CPQ_ATTR_SEARCH_MAX_CHOICES, or 5 when unset or not an int."""
    value = getattr(get_settings(), "cpq_attr_search_max_choices", _DEFAULT_MAX_CHOICES)
    return value if isinstance(value, int) and value >= 2 else _DEFAULT_MAX_CHOICES


def _budget_s() -> float:
    """ARYX_CPQ_ATTR_SEARCH_BUDGET_S, or 25 s when unset or not a positive number."""
    value = getattr(get_settings(), "cpq_attr_search_budget_s", _DEFAULT_BUDGET_S)
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    return float(value) if ok else _DEFAULT_BUDGET_S


def _names_a_product(engine: Any, req: AskRequest, reader: Any) -> bool:
    """True when the message itself names a product -- then the product wins."""
    try:
        if engine.detect_product_mention(req.question, {}, reader, req.workspace_id):
            return True
        return bool(engine.resolve_product_hint(reader, req.workspace_id, req.question))
    except Exception as exc:  # noqa: BLE001 -- a failed check must not block the search
        logger.warning("attribute_search: product-mention check failed", exc_info=True)
        raven_log("WARN", "P3", "ask.attr_search.product_check_failed treated as no product named",
                  error_code="ARYX_ASK_ATTR_SEARCH_PRODUCT_CHECK_FAILED",
                  context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                           "backoff_ms": 0, "recovery_selected": "continue_search", "fallback_target": None,
                           "exit_condition": "exception", "result": "degraded"})
        return False


def _list_response(req: AskRequest, route_meta: Any, res: AttributeSearchResult,
                   t0: float) -> dict[str, Any]:
    """Answer with the list of matches; the session is left unchanged."""
    return {
        "answer": _format_answer(res),
        "terms": [],
        "tools_called": ["find_products_by_attribute()"],
        "usage": {
            "prompt_tokens": route_meta.prompt_tokens,
            "completion_tokens": route_meta.completion_tokens,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "menial_model": "deterministic",
            "answer_model": route_meta.model_id or "deterministic",
        },
        "grounding": None,
        "session_data": req.session_data or {},
        "cpq_payload": {"attribute_search_results": {
            "labels": res.labels, "value": res.value,
            "products": res.products, "offered_values": res.offered_values,
        }},
    }


def decide(req: AskRequest, reader: Any, route_meta: Any, res: AttributeSearchResult,
           anchor_question: str | None = None, t0: float | None = None) -> dict[str, Any]:
    """Pick the next step for a search result (see the module docstring).

    `anchor_question` is the customer's original message when this turn is a
    follow-up reply; it defaults to this turn's question.
    """
    t0 = time.monotonic() if t0 is None else t0
    anchor = anchor_question or req.question
    # A quote can only start from a catalog family (not a Data Table model).
    families = [p for p in res.products if "catalog_menu" in p.get("sources", [])]
    if res.value is None and not res.feature_only:
        if res.offered_values:
            return _handoff.ask_for_value(req, route_meta, res, _format_answer(res))
        return _list_response(req, route_meta, res, t0)
    if len(families) == 1:
        return _handoff.start_quote(req, reader, route_meta, families[0],
                                    _format_answer(res), anchor)
    if 2 <= len(families) <= _max_choices():
        return _handoff.offer_families(req, route_meta, res, families, anchor)
    if len(families) > _max_choices():
        return _handoff.ask_for_family(req, route_meta, res, families, anchor)
    return _list_response(req, route_meta, res, t0)


def _route_attribute_search(req: AskRequest, reader: Any, route_meta: Any) -> dict[str, Any] | None:
    """Answer an attribute-first question, or None to fall back to the quote path.

    Args:
        req: The /ask request.
        reader: Graph reader, used to load each family's catalog menus.
        route_meta: AskRouteDecision carrying attribute_label/attribute_value.

    Returns:
        The /ask response dict, or None (see the module docstring).
    """
    from aryx.api import ask_api as _ask_api_module

    t0 = time.monotonic()
    engine = _ask_api_module._cpq_engine
    if _names_a_product(engine, req, reader):
        logger.info("attribute_search: message names a product → quote path")
        raven_log("DEBUG", "P4", "ask.attr_search.skipped message names a product, quote path", context={
            "selected_option": "quote", "available_options": ["attribute_search", "quote"],
            "reason_code": "PRODUCT_NAMED", "attribute_label": route_meta.attribute_label})
        return None
    _budget = _budget_s()
    try:
        res = run_with_budget(lambda: find_products_by_attribute(
            route_meta.attribute_label or "", route_meta.attribute_value,
            workspace_id=req.workspace_id, reader=reader, engine=engine,
        ), budget_s=_budget)
    except BudgetExceeded as exc:
        logger.warning("attribute_search: cold catalog cache, over budget → quote path "
                       "(the lookup keeps warming the cache)")
        raven_log("WARN", "P3", "ask.attr_search.over_budget lookup over budget or busy, quote path",
                  error_code="ARYX_ASK_ATTR_SEARCH_OVER_BUDGET",
                  context={"dependency_name": "attribute_search_lookup", "operation": "find_products_by_attribute",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "fallback_quote",
                           "error_class": type(exc).__name__, "attempt": 1, "budget_s": _budget,
                           "attribute_label": route_meta.attribute_label})
        return None
    except Exception as exc:  # noqa: BLE001 -- never let a search error break the turn
        logger.warning(
            "attribute_search: lookup failed label=%r value=%r: %s",
            route_meta.attribute_label, route_meta.attribute_value, exc, exc_info=True,
        )
        raven_log("ERROR", "P2", "ask.attr_search.lookup_failed search failed, quote path used instead",
                  error_code="ARYX_ASK_ATTR_SEARCH_FAILED",
                  context={"dependency_name": "attribute_search_lookup", "operation": "find_products_by_attribute",
                           "duration_ms": int((time.monotonic() - t0) * 1000), "result": "fallback_quote",
                           "error_class": type(exc).__name__, "attempt": 1,
                           "attribute_label": route_meta.attribute_label})
        return None
    raven_log("DEBUG", "P4", "ask.attr_search.lookup done", context={
        "selected_option": "decide" if res is not None else "quote",
        "available_options": ["decide", "quote"],
        "reason_code": "RESULT_FOUND" if res is not None else "NOT_GROUNDED",
        "attribute_label": route_meta.attribute_label,
        "duration_ms": int((time.monotonic() - t0) * 1000)})
    if res is None:
        return None
    return decide(req, reader, route_meta, res, t0=t0)
