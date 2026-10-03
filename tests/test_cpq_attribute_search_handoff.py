"""Attribute-first discovery, phase 4: from search result to quote.

1 family -> start its quote with the value filled in; 2..N -> numbered
choice (step 1 resolves the reply, seeds remembered per family); >N ->
"which product family?"; no value -> ask which value; a product named in
the message -> None (normal quote path).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aryx.api.ask_api import AskRequest
from aryx.api.ask_attribute_search import _route_attribute_search
from aryx.cpq.attribute_search.lookup import AttributeSearchResult
from aryx.cpq.intent_gateway.intent_gateway import AskRouteDecision
from aryx.cpq.state import CpqSession

_H = "aryx.api.ask_attribute_search"
_QUOTE = "aryx.api.ask_response_building.ask_finish_cpq_result._route_quote"
_Q = "I want a product that has ATT as a carrier"


@pytest.fixture(autouse=True)
def engine():
    eng = MagicMock()
    eng.detect_product_mention.return_value = ""
    eng.resolve_product_hint.return_value = None
    with patch("aryx.api.ask_api._cpq_engine", eng), \
         patch("aryx.api.ask_core_helpers._persist_cpq_history") as persist:
        eng.persist = persist
        yield eng


def _req(q: str = _Q) -> AskRequest:
    return AskRequest(question=q, workspace_id=704, history=[], session_data={})


def _meta(value: str | None = "ATT", qty: int | None = None, country: str | None = None):
    return AskRouteDecision(route="attribute_search", confidence="high", clarifying_question=None,
                            rationale="", attribute_label="carrier", attribute_value=value,
                            quantity=qty, country=country)


def _family(name: str, vn: str = "wirelessCarrier") -> dict:
    return {"model": name, "base_models": [], "attributes": [vn], "sources": ["catalog_menu"],
            "labels": ["Wireless Carrier"], "values": ["ATT/FirstNet (provided by Motorola)"],
            "seeds": [{"vn": vn, "item_value": "ATT/FIRSTNET",
                       "display": "ATT/FirstNet (provided by Motorola)", "select_type": "single"}]}


def _res(products, value="ATT", feature_only=False, offered=None) -> AttributeSearchResult:
    return AttributeSearchResult(phrase="carrier", labels=["Wireless Carrier"], value=value,
                                 products=products, offered_values=offered or [],
                                 feature_only=feature_only)


def _run(res, meta=None, q=_Q):
    with patch(f"{_H}.find_products_by_attribute", return_value=res), \
         patch(_QUOTE, return_value={"answer": "Which country is the customer in?",
                                     "session_data": {"x": 1}}) as quote:
        out = _route_attribute_search(_req(q), object(), meta or _meta())
    return out, quote


def test_one_family_starts_its_quote_with_the_value_filled_in():
    out, quote = _run(_res([_family("aSTRO25_bom")]))
    req2, _reader, meta2 = quote.call_args[0]
    session = CpqSession.from_dict(req2.session_data)
    assert session.product_name == "aSTRO25_bom"
    assert session.filled == {"wirelessCarrier": "ATT/FIRSTNET"}
    assert session.filled_source == {"wirelessCarrier": "hint"}
    assert session.product_anchor_question == _Q
    assert meta2.route == "quote"
    assert out["answer"] == (
        "aSTRO25_bom offers Wireless Carrier: ATT/FirstNet (provided by Motorola).\n\n"
        "Which country is the customer in?"
    )


def test_quantity_and_country_from_the_first_message_are_kept():
    _, quote = _run(_res([_family("aSTRO25_bom")]), meta=_meta(qty=5, country="USA"))
    req2, _reader, meta2 = quote.call_args[0]
    session = CpqSession.from_dict(req2.session_data)
    assert (session.product_quantity, session.country) == (5, "United States")
    assert (meta2.quantity, meta2.country) == (5, "USA")


def test_two_families_are_offered_as_a_numbered_choice():
    out, quote = _run(_res([_family("aSTRO25_bom"), _family("MOTOTRBO", vn="carrierM")]))
    quote.assert_not_called()
    assert out["answer"] == (
        "2 product families offer Wireless Carrier 'ATT':\n\n1. aSTRO25_bom\n2. MOTOTRBO\n\n"
        "Which one would you like to quote?"
    )
    session = CpqSession.from_dict(out["session_data"])
    assert session.pending_anchor == "product"
    assert session.pending_scope_kind == "product_suggestions"
    assert session.pending_scope_candidates == ["aSTRO25_bom", "MOTOTRBO"]
    assert set(session.attribute_search_seeds) == {"aSTRO25_bom", "MOTOTRBO"}
    assert session.product_anchor_question == _Q
    assert session.filled == {}


def test_more_than_the_cap_asks_which_family():
    fams = [_family(f"FAM{i}", vn=f"v{i}") for i in range(7)]
    out, quote = _run(_res(fams))
    quote.assert_not_called()
    assert out["answer"] == (
        "7 product families offer Wireless Carrier 'ATT', including "
        "FAM0, FAM1, FAM2, FAM3, FAM4 and 2 more. Which product family would you like to quote?"
    )
    session = CpqSession.from_dict(out["session_data"])
    assert session.pending_anchor == "product"
    assert len(session.attribute_search_seeds) == 7


def test_cap_comes_from_settings():
    fams = [_family(f"FAM{i}", vn=f"v{i}") for i in range(3)]
    with patch(f"{_H}.get_settings", return_value=MagicMock(cpq_attr_search_max_choices=2)):
        out, _ = _run(_res(fams))
    assert "Which product family would you like to quote?" in out["answer"]


def test_label_only_asks_for_the_value_and_remembers_the_attribute():
    out, quote = _run(_res([_family("aSTRO25_bom")], value=None, offered=["ATT", "VERIZON"]),
                      meta=_meta(value=None))
    quote.assert_not_called()
    assert out["answer"].endswith("Which one do you need?")
    session = CpqSession.from_dict(out["session_data"])
    assert session.pending_attribute_label == "carrier"
    assert session.pending_anchor == ""


def test_yes_no_feature_with_one_family_starts_the_quote():
    fam = _family("aSTRO25_bom", vn="dualSim")
    fam["seeds"][0].update(item_value="true", display="Yes", select_type="boolean")
    _, quote = _run(_res([fam], value=None, feature_only=True))
    session = CpqSession.from_dict(quote.call_args[0][0].session_data)
    assert session.filled == {"dualSim": "true"}


def test_data_table_only_models_are_listed_not_quoted():
    dt = {"model": "APX1000", "base_models": ["H45"], "labels": ["Carrier Selection"],
          "attributes": ["c"], "values": ["ATT"], "sources": ["data_table"], "seeds": []}
    out, quote = _run(_res([dt]))
    quote.assert_not_called()
    assert out["answer"] == "APX1000 offers Carrier Selection: ATT."


def test_message_naming_a_product_goes_to_the_quote_path(engine):
    engine.detect_product_mention.return_value = "APX NEXT"
    with patch(f"{_H}.find_products_by_attribute") as find:
        assert _route_attribute_search(_req("APX Next with ATT carrier"), object(), _meta()) is None
    find.assert_not_called()


def test_product_hint_also_counts_as_naming_a_product(engine):
    engine.resolve_product_hint.return_value = ("family", "aSTRO25_bom")
    with patch(f"{_H}.find_products_by_attribute") as find:
        assert _route_attribute_search(_req(), object(), _meta()) is None
    find.assert_not_called()


def test_failed_product_check_does_not_block_the_search(engine):
    engine.detect_product_mention.side_effect = RuntimeError("db down")
    out, _ = _run(_res([_family("aSTRO25_bom")]))
    assert out["answer"].startswith("aSTRO25_bom offers")


def test_answered_turns_are_saved_to_history(engine):
    _run(_res([_family("A"), _family("B", vn="v2")]))
    engine.persist.assert_called_once()


def test_family_without_values_to_fill_still_starts_its_quote():
    fam = _family("aSTRO25_bom")
    fam["seeds"] = []
    _, quote = _run(_res([fam], value=None, feature_only=True))
    session = CpqSession.from_dict(quote.call_args[0][0].session_data)
    assert session.product_name == "aSTRO25_bom"
    assert session.filled == {}
