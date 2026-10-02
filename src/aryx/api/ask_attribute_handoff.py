"""Turn an attribute-search result into the next step of a quote (phase 4).

- One family matches: start a normal quote for it, with the matched value
  already filled in (cpq/attribute_search/seeds.py).
- 2..N families: offer them as a numbered choice. Uses the same
  `pending_anchor="product"` + `product_suggestions` scope the "which
  product family?" prompt uses, so step 1 resolves the reply; the values
  for each family are remembered in `session.attribute_search_seeds` and
  step 1 fills them in for the family picked.
- More than N: ask which product family, same remembered values.
- Label only ("which products are available for carrier selection"): list
  the values on offer and remember the attribute in
  `session.pending_attribute_label`, so the reply is read as the value.

Quantity and country from the first message are kept on the session.
`_persist_cpq_history` and `_route_quote` are read through their MODULE
objects so tests can patch them, same convention as the step-1 prompts.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from aryx.api import ask_core_helpers as _ask_core_helpers_module
from aryx.api.ask_attribute_search_answers import _MAX_LISTED_PRODUCTS, _criteria, _listed
from aryx.api.ask_request_models import AskRequest
from aryx.api.ask_response_building import ask_finish_cpq_result as _finish_module
from aryx.cpq.attribute_search.lookup import AttributeSearchResult
from aryx.cpq.attribute_search.seeds import seed_values
from aryx.cpq.governance_and_sibling_exclusivity.country import is_recognized_country
from aryx.cpq.pending_scope.pending_scope import set_pending_scope
from aryx.cpq.quantity.quantity_patterns import is_valid_product_quantity
from aryx.cpq.state import CpqSession


def _new_session(anchor_question: str, route_meta: Any) -> CpqSession:
    """A fresh session carrying the first message, quantity and country."""
    session = CpqSession()
    session.product_anchor_question = anchor_question
    qty = route_meta.quantity
    if isinstance(qty, int) and not isinstance(qty, bool) and is_valid_product_quantity(qty):
        session.product_quantity = qty
    country = is_recognized_country(route_meta.country) if route_meta.country else None
    if country:
        session.country = country
    return session


def _response(req: AskRequest, answer: str, session: CpqSession, res: AttributeSearchResult,
              tool: str) -> dict[str, Any]:
    """An /ask response for a turn this module fully answers."""
    _ask_core_helpers_module._persist_cpq_history(req.workspace_id, req.question, answer)
    return {
        "answer": answer, "terms": [], "tools_called": [tool],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
                  "menial_model": "deterministic", "answer_model": "deterministic"},
        "grounding": None, "session_data": session.to_dict(),
        "cpq_payload": {"attribute_search_results": {
            "labels": res.labels, "value": res.value, "products": res.products,
            "offered_values": res.offered_values,
        }},
    }


def start_quote(req: AskRequest, reader: Any, route_meta: Any, family: dict[str, Any],
                intro: str, anchor_question: str) -> dict[str, Any]:
    """Start a normal quote for `family` with its matched values filled in."""
    session = _new_session(anchor_question, route_meta)
    session.product_name = family["model"]
    seed_values(session, family["seeds"])
    quote_req = req.model_copy(update={"session_data": session.to_dict()})
    out = dict(_finish_module._route_quote(
        quote_req, reader, dataclasses.replace(route_meta, route="quote"),
    ))
    out["answer"] = f"{intro}\n\n{out.get('answer') or ''}".strip()
    return out


def _pending_family_session(req: AskRequest, route_meta: Any, families: list[dict[str, Any]],
                            anchor_question: str) -> CpqSession:
    """Session waiting for the customer to pick one of `families`."""
    session = _new_session(anchor_question, route_meta)
    session.pending_anchor = "product"
    names = [f["model"] for f in families]
    set_pending_scope(session, kind="product_suggestions", candidates=names,
                      origin_question=anchor_question, asked_turn=session.turn)
    session.attribute_search_seeds = {f["model"]: f["seeds"] for f in families}
    return session


def offer_families(req: AskRequest, route_meta: Any, res: AttributeSearchResult,
                   families: list[dict[str, Any]], anchor_question: str) -> dict[str, Any]:
    """Offer 2..N matching families as a numbered choice."""
    session = _pending_family_session(req, route_meta, families, anchor_question)
    numbered = "\n".join(f"{i}. {f['model']}" for i, f in enumerate(families, 1))
    answer = (f"{len(families)} product families offer {_criteria(res)}:\n\n{numbered}\n\n"
              "Which one would you like to quote?")
    return _response(req, answer, session, res, "attribute_search_offer_families()")


def ask_for_family(req: AskRequest, route_meta: Any, res: AttributeSearchResult,
                   families: list[dict[str, Any]], anchor_question: str) -> dict[str, Any]:
    """Too many families to list as choices: ask which one."""
    session = _pending_family_session(req, route_meta, families, anchor_question)
    names = _listed([f["model"] for f in families], min(5, _MAX_LISTED_PRODUCTS))
    answer = (f"{len(families)} product families offer {_criteria(res)}, including {names}. "
              "Which product family would you like to quote?")
    return _response(req, answer, session, res, "attribute_search_ask_family()")


def ask_for_value(req: AskRequest, route_meta: Any, res: AttributeSearchResult,
                  answer: str) -> dict[str, Any]:
    """List the values on offer and read the next reply as the value."""
    session = _new_session(req.question, route_meta)
    session.pending_attribute_label = res.phrase
    return _response(req, answer, session, res, "attribute_search_ask_value()")
