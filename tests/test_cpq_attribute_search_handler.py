"""Attribute-first discovery, phase 2: the /ask handler for route=attribute_search.

Lists the products that offer the requested attribute value (or, with no
value, the values on offer), and returns None when the label cannot be
grounded so run_ask falls back to the normal quote path.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_api import AskRequest, run_ask
from aryx.api.ask_attribute_search import _route_attribute_search
from aryx.cpq.attribute_search.lookup import AttributeSearchResult
from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision

_H = "aryx.api.ask_attribute_search"


@pytest.fixture(autouse=True)
def _no_product_named_and_no_history():
    """No product named in the message; history writes stubbed (no DB)."""
    engine = MagicMock()
    engine.detect_product_mention.return_value = ""
    engine.resolve_product_hint.return_value = None
    with patch("aryx.api.ask_api._cpq_engine", engine), \
         patch("aryx.api.ask_core_helpers._persist_cpq_history"):
        yield engine


def _req(question: str = "I want a product that has ATT as a carrier") -> AskRequest:
    return AskRequest(question=question, workspace_id=3, history=[], session_data={"k": "v"})


def _meta(label: str | None = "carrier", value: str | None = "ATT") -> AskRouteDecision:
    return AskRouteDecision(
        route="attribute_search", confidence="high", clarifying_question=None,
        rationale="", attribute_label=label, attribute_value=value,
    )


def _product(model: str, values: list[str]) -> dict:
    return {"model": model, "base_models": [], "labels": ["Carrier Selection"],
            "attributes": ["carrierSel_astro"], "values": values}


def _result(products, value="ATT", offered=None) -> AttributeSearchResult:
    return AttributeSearchResult(
        phrase="carrier", labels=["Carrier Selection"], value=value,
        products=products, offered_values=offered or [],
    )


def test_returns_none_when_label_cannot_be_grounded():
    with patch(f"{_H}.find_products_by_attribute", return_value=None):
        assert _route_attribute_search(_req(), object(), _meta()) is None


def test_returns_none_when_lookup_raises():
    with patch(f"{_H}.find_products_by_attribute", side_effect=RuntimeError("db down")):
        assert _route_attribute_search(_req(), object(), _meta()) is None


def test_lists_matching_products():
    res = _result([_product("APX1000", ["ATT/FIRSTNET"]), _product("APXNEXT", ["ATT"])])
    reader = object()
    with patch(f"{_H}.find_products_by_attribute", return_value=res) as find:
        out = _route_attribute_search(_req(), reader, _meta())
    from aryx.api import ask_api
    find.assert_called_once_with("carrier", "ATT", workspace_id=3, reader=reader,
                                 engine=ask_api._cpq_engine)
    assert out["answer"] == "2 products offer Carrier Selection 'ATT': APX1000, APXNEXT."
    assert out["cpq_payload"]["attribute_search_results"]["products"] == res.products
    assert out["session_data"] == {"k": "v"}
    assert out["tools_called"] == ["find_products_by_attribute()"]


def test_single_product_phrasing():
    res = _result([_product("APX1000", ["ATT/FIRSTNET"])])
    with patch(f"{_H}.find_products_by_attribute", return_value=res):
        out = _route_attribute_search(_req(), object(), _meta())
    assert out["answer"] == "APX1000 offers Carrier Selection: ATT/FIRSTNET."


def test_long_product_lists_are_truncated():
    res = _result([_product(f"M{i:02d}", ["ATT"]) for i in range(25)])
    with patch(f"{_H}.find_products_by_attribute", return_value=res):
        out = _route_attribute_search(_req(), object(), _meta())
    assert out["answer"].startswith("25 products offer Carrier Selection 'ATT': M00, M01")
    assert out["answer"].endswith("and 5 more.")


def test_no_matching_product_says_so():
    with patch(f"{_H}.find_products_by_attribute", return_value=_result([])):
        out = _route_attribute_search(_req(), object(), _meta())
    assert out["answer"] == "I couldn't find any product with Carrier Selection 'ATT'."


def test_label_only_lists_offered_values_and_asks():
    res = _result([_product("APX1000", ["ATT"])], value=None, offered=["ATT", "VERIZON"])
    with patch(f"{_H}.find_products_by_attribute", return_value=res):
        out = _route_attribute_search(
            _req("Which products are available for carrier selection"), object(),
            _meta("carrier selection", None),
        )
    assert out["answer"] == (
        "Products offer these Carrier Selection options: ATT, VERIZON. Which one do you need?"
    )


def test_label_only_with_nothing_offered():
    with patch(f"{_H}.find_products_by_attribute", return_value=_result([], value=None)):
        out = _route_attribute_search(_req(), object(), _meta("carrier selection", None))
    assert out["answer"] == "I couldn't find any product that offers Carrier Selection."


# ── run_ask dispatch ─────────────────────────────────────────────────────────


def _run(meta: AskRouteDecision, handler_result):
    cfg = MagicMock(cpq_intent_mode="llm_first", cpq_intent_timeout_s=5.0)
    with patch("aryx.api.ask_api.get_settings", return_value=cfg), \
         patch("aryx.api.ask_api.hard_off_topic", return_value=False), \
         patch("aryx.api.ask_api.detect_feature_region_search", return_value=(None, None, None)), \
         patch("aryx.api.ask_api.soft_quote_heuristic", return_value=False), \
         patch("aryx.api.ask_api.classify_ask_route", return_value=meta), \
         patch("aryx.api.ask_api.mark_top_level_route_used"), \
         patch("aryx.api.ask_core_helpers._reader", return_value=MagicMock()), \
         patch("aryx.api.ask_response_building.ask_finish_cpq_result._deterministic_cpq_gate",
               return_value=True), \
         patch("aryx.api.ask_run_ask._route_attribute_search",
               return_value=handler_result) as handler, \
         patch("aryx.api.ask_run_ask._route_quote", return_value={"answer": "q"}) as quote:
        out = run_ask(_req())
    return out, handler, quote


def test_run_ask_uses_handler_answer_when_it_has_one():
    out, handler, quote = _run(_meta(), {"answer": "APX1000 offers Carrier Selection: ATT/FIRSTNET."})
    assert out["answer"].startswith("APX1000")
    handler.assert_called_once()
    quote.assert_not_called()


def test_run_ask_falls_back_to_quote_when_handler_returns_none():
    meta = _meta()
    meta.quantity, meta.country = 5, "Germany"
    out, _, quote = _run(meta, None)
    assert out == {"answer": "q"}
    passed = quote.call_args[0][2]
    assert passed.route == "quote"
    assert (passed.quantity, passed.country) == (5, "Germany")


def test_single_product_names_every_matched_label_and_option():
    prod = {"model": "aSTRO25_bom", "base_models": [], "attributes": [],
            "labels": ["Carrier Selection", "Wireless Carrier"],
            "values": ["ATT/FirstNet (provided by Motorola)"]}
    res = AttributeSearchResult(phrase="carrier", labels=prod["labels"], value="ATT",
                                products=[prod])
    with patch(f"{_H}.find_products_by_attribute", return_value=res):
        out = _route_attribute_search(_req(), object(), _meta())
    assert out["answer"] == (
        "aSTRO25_bom offers Carrier Selection and Wireless Carrier: "
        "ATT/FirstNet (provided by Motorola)."
    )


def test_no_match_across_several_labels_joins_them_with_or():
    res = AttributeSearchResult(phrase="carrier", labels=["Carrier Selection", "Wireless Carrier"],
                                value="Sprint", products=[])
    with patch(f"{_H}.find_products_by_attribute", return_value=res):
        out = _route_attribute_search(_req(), object(), _meta())
    assert out["answer"] == (
        "I couldn't find any product with Carrier Selection or Wireless Carrier 'Sprint'."
    )


def _feature(products) -> AttributeSearchResult:
    return AttributeSearchResult(phrase="dual active sim", labels=["Enable Dual Active Sim?"],
                                 value=None, products=products, feature_only=True)


def test_feature_with_one_product_says_it_offers_it():
    prod = {"model": "aSTRO25_bom", "base_models": [], "attributes": [],
            "labels": ["Enable Dual Active Sim?"], "values": ["Yes"]}
    with patch(f"{_H}.find_products_by_attribute", return_value=_feature([prod])):
        out = _route_attribute_search(_req(), object(), _meta("dual active sim", None))
    assert out["answer"] == "aSTRO25_bom offers Enable Dual Active Sim?"


def test_feature_with_several_products_lists_them():
    prods = [{"model": m, "base_models": [], "attributes": [],
              "labels": ["Enable Dual Active Sim?"], "values": ["Yes"]} for m in ("A", "B")]
    with patch(f"{_H}.find_products_by_attribute", return_value=_feature(prods)):
        out = _route_attribute_search(_req(), object(), _meta("dual active sim", None))
    assert out["answer"] == "2 products offer Enable Dual Active Sim?: A, B."
