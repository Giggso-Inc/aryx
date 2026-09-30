"""translate_containment_edges -- maps raw graph CONTAINS edges onto
resolved-entity pairs directly, no FK-guessing needed since the XML nesting
is already ground truth.
"""
from __future__ import annotations

from aryx.cpq_ingestion.raw_graph.containment_relate import translate_containment_edges
from aryx.cpq_ingestion.raw_graph.models import RawEdge


def test_translates_one_edge_when_both_endpoints_resolved():
    edges = [RawEdge(source_id=0, target_id=1, name="CONTAINS")]
    mapping = {0: 100, 1: 101}

    [rel] = translate_containment_edges(edges, mapping)

    assert rel.source_entity_id == 100
    assert rel.target_entity_id == 101
    assert rel.name == "CONTAINS"


def test_default_confidence_is_one():
    edges = [RawEdge(source_id=0, target_id=1, name="CONTAINS")]

    [rel] = translate_containment_edges(edges, {0: 100, 1: 101})

    assert rel.confidence == 1.0


def test_custom_confidence_is_applied_to_every_relationship():
    edges = [
        RawEdge(source_id=0, target_id=1, name="CONTAINS"),
        RawEdge(source_id=1, target_id=2, name="CONTAINS"),
    ]

    rels = translate_containment_edges(edges, {0: 100, 1: 101, 2: 102}, confidence=0.8)

    assert all(r.confidence == 0.8 for r in rels)


def test_skips_edge_when_source_endpoint_unresolved():
    edges = [RawEdge(source_id=0, target_id=1, name="CONTAINS")]
    mapping = {1: 101}  # node 0 never resolved into an entity

    assert translate_containment_edges(edges, mapping) == []


def test_skips_edge_when_target_endpoint_unresolved():
    edges = [RawEdge(source_id=0, target_id=1, name="CONTAINS")]
    mapping = {0: 100}  # node 1 never resolved into an entity

    assert translate_containment_edges(edges, mapping) == []


def test_one_unresolved_edge_does_not_block_others():
    edges = [
        RawEdge(source_id=0, target_id=1, name="CONTAINS"),  # target unresolved
        RawEdge(source_id=2, target_id=3, name="CONTAINS"),  # both resolved
    ]
    mapping = {0: 100, 2: 102, 3: 103}

    rels = translate_containment_edges(edges, mapping)

    assert len(rels) == 1
    assert rels[0].source_entity_id == 102
    assert rels[0].target_entity_id == 103


def test_deduplicates_edges_that_collapse_onto_the_same_entity_pair():
    """Two raw Customer nodes both resolved (deduped) into entity 100; two
    separate PurchaseOrder->Customer raw edges must become one relationship,
    not two identical ones."""
    edges = [
        RawEdge(source_id=0, target_id=1, name="CONTAINS"),
        RawEdge(source_id=2, target_id=3, name="CONTAINS"),
    ]
    # Both source nodes resolved to the same PurchaseOrder entity (200);
    # both target nodes resolved to the same, deduplicated Customer entity (100).
    mapping = {0: 200, 1: 100, 2: 200, 3: 100}

    rels = translate_containment_edges(edges, mapping)

    assert len(rels) == 1
    assert rels[0].source_entity_id == 200
    assert rels[0].target_entity_id == 100


def test_distinct_edge_names_between_same_pair_are_not_deduplicated():
    edges = [
        RawEdge(source_id=0, target_id=1, name="CONTAINS"),
        RawEdge(source_id=0, target_id=1, name="REFERENCES"),
    ]
    mapping = {0: 100, 1: 101}

    rels = translate_containment_edges(edges, mapping)

    assert {r.name for r in rels} == {"CONTAINS", "REFERENCES"}


def test_empty_edges_returns_empty_list():
    assert translate_containment_edges([], {0: 100}) == []


def test_empty_mapping_skips_every_edge():
    edges = [RawEdge(source_id=0, target_id=1, name="CONTAINS")]

    assert translate_containment_edges(edges, {}) == []
