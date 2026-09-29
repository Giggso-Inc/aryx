"""Pure XML -> raw graph projection (Pass 1).

No I/O, no database, no entity-classification heuristic. This mirrors the
manually-scripted "Scenario A" walk that was run live against FalkorDB
during local testing (see docs referenced in the package README) and
verified to produce 14 nodes / 13 edges for the plural-wrapper sample XML
and 12 nodes / 11 edges for the same data with wrapper tags removed —
confirming, unlike ``_xml_to_csvs``, that this projector's output does not
depend on whether the source XML wraps repeated children in a plural tag.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import defusedxml.ElementTree as defused_ET

from aryx.cpq_ingestion.constants import RAW_EDGE_CONTAINS, RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode


def _strip_ns(tag: str) -> str:
    """Drop an XML namespace prefix (``{uri}tag`` -> ``tag``)."""
    return tag.split("}")[-1] if "}" in tag else tag


def project_xml_to_raw_graph(data: bytes) -> RawGraphProjection:
    """Walk an XML document into raw graph nodes and edges.

    Rule: every element becomes one node labeled by its (namespace-stripped)
    tag; every parent -> child element relationship becomes one
    ``CONTAINS`` edge; an element's own attributes become node properties;
    a leaf element's (no-children) non-empty text becomes a ``text``
    property. No classification, no deduplication, no exclusion — this is
    the raw layer, deliberately unfiltered.

    Args:
        data: Raw XML document bytes.

    Returns:
        Every node and edge discovered, in document order. Node ids are
        assigned sequentially starting at 1 and are only meaningful within
        this single projection — they are not stable across runs and are
        not the same id space as ``aryx_entity.id``.
    """
    root = defused_ET.fromstring(data)

    nodes: list[RawNode] = []
    edges: list[RawEdge] = []
    next_id = [0]

    def walk(elem: ET.Element, parent_id: int | None) -> None:
        next_id[0] += 1
        my_id = next_id[0]
        tag = _strip_ns(elem.tag)
        properties: dict[str, object] = dict(elem.attrib)
        children = list(elem)
        if not children:
            text = (elem.text or "").strip()
            if text:
                properties[RAW_PROP_TEXT] = text
        nodes.append(RawNode(id=my_id, tag=tag, properties=properties))
        if parent_id is not None:
            edges.append(RawEdge(source_id=parent_id, target_id=my_id, name=RAW_EDGE_CONTAINS))
        for child in children:
            walk(child, my_id)

    walk(root, None)
    return RawGraphProjection(nodes=nodes, edges=edges)
