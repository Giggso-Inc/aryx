"""Match-key inference for raw graph tags: heuristic-first, LLM fallback only
when the heuristic finds nothing, default-to-first-key as a last resort.

Mirrors the coverage shape of doc_discovery_types.py's _infer_type tests,
adapted for property-dict input instead of a CSV sample.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.cpq_ingestion.raw_graph.match_key_inference import (
    _guess_key_prop,
    infer_match_keys_for_tag,
)
from aryx.cpq_ingestion.raw_graph.models import RawNode


def _settings(id_like="id,uuid,guid,key", suffixes="_code,_id,_key,_num,_ref,_no,_cage"):
    mock = MagicMock()
    mock.id_like_column_names = id_like
    mock.fk_key_suffixes = suffixes
    return mock


# ── _guess_key_prop (pure heuristic) ────────────────────────────────────────

def test_guess_key_prop_matches_exact_id_like_name():
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()):
        assert _guess_key_prop({"Id": "PO-1001", "Amount": "100"}) == "Id"


def test_guess_key_prop_matches_key_suffix():
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()):
        assert _guess_key_prop({"customer_ref": "C-42", "notes": "x"}) == "customer_ref"


def test_guess_key_prop_returns_none_when_nothing_matches():
    """"Sku" matches neither the id-like-name list nor a key suffix by
    default -- this is the exact gap the LLM fallback exists to cover."""
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()):
        assert _guess_key_prop({"Sku": "WIDGET-A", "Qty": "10"}) is None


def test_guess_key_prop_empty_properties_returns_none():
    assert _guess_key_prop({}) is None


# ── infer_match_keys_for_tag (full flow) ────────────────────────────────────

def test_infer_uses_heuristic_without_calling_llm_when_id_present():
    nodes = [RawNode(id=0, tag="PurchaseOrder", properties={"Id": "PO-1001"})]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat") as mock_llm:
        result = infer_match_keys_for_tag("PurchaseOrder", nodes)

    mock_llm.assert_not_called()
    assert result == {"ontology_type": "PurchaseOrder", "match_keys": ["Id"]}


def test_infer_falls_back_to_llm_when_heuristic_finds_nothing():
    nodes = [RawNode(id=0, tag="LineItem", properties={"Sku": "WIDGET-A", "Qty": "10"})]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat",
               return_value=['{"match_key":"Sku"}']) as mock_llm:
        result = infer_match_keys_for_tag("LineItem", nodes)

    mock_llm.assert_called_once()
    assert result == {"ontology_type": "LineItem", "match_keys": ["Sku"]}


def test_infer_defaults_to_first_property_when_llm_also_fails():
    nodes = [RawNode(id=0, tag="LineItem", properties={"Sku": "WIDGET-A", "Qty": "10"})]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat",
               side_effect=RuntimeError("LLM unavailable")):
        result = infer_match_keys_for_tag("LineItem", nodes)

    assert result == {"ontology_type": "LineItem", "match_keys": ["Sku"]}


def test_infer_llm_returning_key_not_in_properties_falls_back_to_default():
    nodes = [RawNode(id=0, tag="LineItem", properties={"Sku": "WIDGET-A"})]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat",
               return_value=['{"match_key":"NotAProperty"}']):
        result = infer_match_keys_for_tag("LineItem", nodes)

    assert result == {"ontology_type": "LineItem", "match_keys": ["Sku"]}


def test_infer_ontology_type_is_always_the_tag_never_llm_derived():
    """Unlike CSV inference, ontology_type is never asked of the LLM --
    RawNode.tag is already the established type convention."""
    nodes = [RawNode(id=0, tag="Customer", properties={"Id": "C-42"})]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()):
        result = infer_match_keys_for_tag("Customer", nodes)

    assert result["ontology_type"] == "Customer"


def test_infer_skips_nodes_with_empty_properties_when_picking_a_sample():
    nodes = [
        RawNode(id=0, tag="Contact", properties={}),
        RawNode(id=1, tag="Contact", properties={"Id": "003CT"}),
    ]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat") as mock_llm:
        result = infer_match_keys_for_tag("Contact", nodes)

    mock_llm.assert_not_called()
    assert result["match_keys"] == ["Id"]


def test_infer_all_nodes_empty_properties_defaults_to_id():
    nodes = [RawNode(id=0, tag="Marker", properties={})]
    with patch("aryx.pipeline.doc_discovery.doc_discovery_types.get_settings",
               return_value=_settings()), \
         patch("aryx.cpq_ingestion.raw_graph.match_key_inference.llm_runtime.chat") as mock_llm:
        result = infer_match_keys_for_tag("Marker", nodes)

    mock_llm.assert_not_called()
    assert result == {"ontology_type": "Marker", "match_keys": ["id"]}
