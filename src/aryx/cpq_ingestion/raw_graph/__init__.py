"""Pass 1: direct XML -> raw knowledge graph (no CSV intermediate).

One XML element becomes one graph node (label = tag); nesting becomes one
CONTAINS edge; attributes and leaf-element text become node properties. No
entity-classification heuristic runs here, so no element can be silently
dropped the way ``_xml_to_csvs``'s entity-detection rule drops elements
under a plural wrapper tag with a single child type (see the package
README for the reference finding this design is based on).
"""
from __future__ import annotations

from aryx.cpq_ingestion.raw_graph.containment_relate import translate_containment_edges
from aryx.cpq_ingestion.raw_graph.match_key_inference import infer_match_keys_for_tag
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawGraphWriteResult, RawNode
from aryx.cpq_ingestion.raw_graph.resolve_adapter import RawGraphConnector, group_nodes_by_tag, parse_record_id
from aryx.cpq_ingestion.raw_graph.resolve_relate import resolve_and_relate_raw_graph
from aryx.cpq_ingestion.raw_graph.store import get_raw_graph_store, write_raw_graph
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

__all__ = [
    "RawEdge",
    "RawGraphConnector",
    "RawGraphProjection",
    "RawGraphWriteResult",
    "RawNode",
    "get_raw_graph_store",
    "group_nodes_by_tag",
    "infer_match_keys_for_tag",
    "parse_record_id",
    "project_xml_to_raw_graph",
    "resolve_and_relate_raw_graph",
    "translate_containment_edges",
    "write_raw_graph",
]
