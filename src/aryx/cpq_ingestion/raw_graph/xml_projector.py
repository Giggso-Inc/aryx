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

import io
import logging
import time

import defusedxml.ElementTree as defused_ET

from aryx.cpq_ingestion.constants import RAW_EDGE_CONTAINS, RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode

logger = logging.getLogger(__name__)

# How often (in elements finished) to log progress during a large parse.
# Live-confirmed incident: a 240MB XML upload looked identical to a hang for
# 15+ minutes -- nothing in this function logged anything between "started"
# and "finished" (or, in that case, never finished at all), so there was no
# way to tell a slow-but-working parse apart from a genuinely stuck one.
_PROGRESS_LOG_INTERVAL = 50_000


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

    Streaming, not DOM: this previously called ``defused_ET.fromstring(data)``
    -- a full in-memory parse that builds the ENTIRE document tree before
    returning anything, holding every element (and the still-undecoded
    source bytes) in memory simultaneously. Live-confirmed: a 240MB XML
    upload stalled for 15+ minutes with near-zero CPU, never reaching this
    function's own node/edge-building step at all, let alone the raw-graph
    write that follows it -- the DOM build itself was the bottleneck, with
    no way to observe progress or bound memory. ``iterparse`` instead walks
    the document incrementally, and ``elem.clear()`` discards each
    element's children/attrib/text as soon as its own node is built, so
    peak memory is bounded by the tree's DEPTH (how deeply nested elements
    are), not the document's total size or element count.

    Args:
        data: Raw XML document bytes.

    Returns:
        Every node and edge discovered. Node ids are assigned sequentially
        in the order elements finish parsing (post-order: children before
        their parent) and are only meaningful within this single
        projection — they are not stable across runs and are not the same
        id space as ``aryx_entity.id``. (The previous DOM-walk implementation
        assigned ids in pre-order instead; nothing downstream depends on
        a particular ordering -- only on id uniqueness and edges
        referencing ids that exist, both still guaranteed here.)
    """
    nodes: list[RawNode] = []
    edges: list[RawEdge] = []
    # Stack of [node_id, has_children] per currently-open element, pushed on
    # "start" and popped on "end" -- XML's well-nested structure means this
    # alone correctly tracks parent/child relationships without needing to
    # stash anything on the Element itself. has_children starts False and is
    # flipped by this element's first child's "start" event, mirroring the
    # original DOM walk's `children = list(elem); if not children: ...`
    # check for whether a leaf's text becomes a property.
    stack: list[list[int | bool]] = []
    next_id = 0
    start = time.monotonic()

    for event, elem in defused_ET.iterparse(io.BytesIO(data), events=("start", "end")):
        if event == "start":
            next_id += 1
            my_id = next_id
            if stack:
                parent_id = stack[-1][0]
                edges.append(RawEdge(source_id=parent_id, target_id=my_id, name=RAW_EDGE_CONTAINS))
                stack[-1][1] = True
            stack.append([my_id, False])
            continue
        # event == "end": this element and all its descendants are now
        # fully parsed -- safe to read its attrib/text and then clear it.
        my_id, has_children = stack.pop()
        tag = _strip_ns(elem.tag)
        properties: dict[str, object] = dict(elem.attrib)
        if not has_children:
            text = (elem.text or "").strip()
            if text:
                properties[RAW_PROP_TEXT] = text
        nodes.append(RawNode(id=my_id, tag=tag, properties=properties))
        elem.clear()
        if len(nodes) % _PROGRESS_LOG_INTERVAL == 0:
            logger.info(
                "project_xml_to_raw_graph: %d element(s) processed, %.1fs elapsed",
                len(nodes), time.monotonic() - start,
            )

    if len(nodes) >= _PROGRESS_LOG_INTERVAL:
        logger.info(
            "project_xml_to_raw_graph: done, %d node(s) / %d edge(s), %.1fs elapsed",
            len(nodes), len(edges), time.monotonic() - start,
        )
    return RawGraphProjection(nodes=nodes, edges=edges)
