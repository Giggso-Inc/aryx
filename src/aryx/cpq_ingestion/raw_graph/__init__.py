"""Pass 1: direct XML -> raw knowledge graph (no CSV intermediate).

One XML element becomes one graph node (label = tag); nesting becomes one
CONTAINS edge; attributes and leaf-element text become node properties. No
entity-classification heuristic runs here, so no element can be silently
dropped the way ``_xml_to_csvs``'s entity-detection rule drops elements
under a plural wrapper tag with a single child type (see the package
README for the reference finding this design is based on).
"""
from __future__ import annotations

from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawGraphWriteResult, RawNode
from aryx.cpq_ingestion.raw_graph.store import get_raw_graph_store, write_raw_graph
from aryx.cpq_ingestion.raw_graph.xml_projector import project_xml_to_raw_graph

__all__ = [
    "RawEdge",
    "RawGraphProjection",
    "RawGraphWriteResult",
    "RawNode",
    "get_raw_graph_store",
    "project_xml_to_raw_graph",
    "write_raw_graph",
]
