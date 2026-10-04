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
from collections.abc import Callable
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as defused_ET

from aryx.cpq_ingestion.constants import RAW_EDGE_CONTAINS, RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.pipeline.orchestrate import PipelineCancelled
from aryx.raven_log import raven_log

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


def project_xml_to_raw_graph(
    data: bytes, should_stop: Callable[[], bool] | None = None,
) -> RawGraphProjection:
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
    upload stalled for 15+ minutes with near-zero CPU, never logging
    anything between function entry and the raw-graph write that follows
    it. The DOM build is the prime suspect given ``fromstring`` cannot
    return or log anything until the whole tree is built, but the
    near-zero-CPU symptom is also consistent with memory-pressure/swap
    thrashing during that build, not pure CPU-bound parsing; this was not
    independently confirmed (a ``py-spy`` stack sample of the hung process
    wasn't obtainable in that environment -- see PR #424's notes), so take
    "the DOM build was the bottleneck" as the best available explanation,
    not a proven root cause.

    ``iterparse`` instead walks the document incrementally, clearing each
    element's children/attrib/text (``elem.clear()``) and detaching it
    from its own parent as soon as its node is built, so the *parse tree
    iterparse itself holds open* no longer grows with the document's total
    size -- only with nesting depth. This removes the DOM's ~30% memory
    overhead on top of the output and restores progress visibility, but it
    does **not** change the function's overall memory complexity: every
    element still becomes one retained ``RawNode``/``RawEdge`` in the
    returned lists, so peak memory is still O(element count) -- a 240MB
    upload with millions of elements still produces a multi-GB result
    either way. For a document large enough that the *output* itself is
    the memory problem, the fix is to stream batches into the raw-graph
    writer instead of materializing the whole projection (not done here).

    Args:
        data: Raw XML document bytes.

    Returns:
        Every node and edge discovered. Node ids are assigned sequentially
        in document (pre-)order -- the order elements *start* parsing --
        and are only meaningful within this single projection: they are
        not stable across runs and are not the same id space as
        ``aryx_entity.id``. ``nodes[i].id == i + 1`` always holds: although
        a node's ``RawNode`` is only fully built once its element *ends*
        (post-order), its slot in the returned list is reserved at *start*
        time and filled in place, so list order matches id order exactly,
        the same as the previous DOM-walk implementation. This matters
        because downstream code (``group_nodes_by_tag`` /
        ``RawGraphConnector.extract``) replays nodes in list order into
        the resolve pipeline, where order can affect entity-id assignment
        and merge tie-breaks for same-tag elements.

    Raises:
        PipelineCancelled: if should_stop is given and reports a cancel,
            checked at the same cadence as progress logging below. Unlike
            count_raw_graph_elements() (a preview-only counter where a
            partial count is still a reasonable answer), a partial
            RawGraphProjection would be silently wrong input to the resolve
            pipeline that consumes it -- so this raises instead of
            returning early (PR #429 review: the Confirm-stage cpq_ingestion
            resolve/relate loop calls this before resolve_and_relate_raw_
            graph(), and that function's own per-tag should_stop checks
            can't help with a cancel that lands during THIS parse -- the
            full parse of a 240MB file took ~40-78s live, all of it
            previously uncancellable).
    """
    nodes: list[RawNode | None] = []
    edges: list[RawEdge] = []
    # Stack of [node_id, has_children, element] per currently-open element,
    # pushed on "start" and popped on "end" -- XML's well-nested structure
    # means this alone correctly tracks parent/child relationships without
    # needing to stash anything on the Element itself. has_children starts
    # False and is flipped by this element's first child's "start" event,
    # mirroring the original DOM walk's `children = list(elem); if not
    # children: ...` check for whether a leaf's text becomes a property.
    # The element reference is kept so a finished child can be detached
    # from its parent's children list (see "end" branch below) -- elem.clear()
    # alone empties the child itself but leaves an empty shell referenced
    # from the parent, which would otherwise accumulate for every sibling.
    stack: list[list[int | bool | Element]] = []
    next_id = 0
    finished = 0
    start = time.monotonic()

    for event, elem in defused_ET.iterparse(io.BytesIO(data), events=("start", "end")):
        if event == "start":
            next_id += 1
            my_id = next_id
            # Reserve this element's list slot now, at pre-order position
            # (my_id - 1), so the final list order matches id order exactly
            # even though the slot is only filled once the element *ends*
            # (post-order) below -- see the docstring's ordering guarantee.
            nodes.append(None)
            if stack:
                parent_id = stack[-1][0]
                edges.append(RawEdge(source_id=parent_id, target_id=my_id, name=RAW_EDGE_CONTAINS))
                stack[-1][1] = True
            stack.append([my_id, False, elem])
            continue
        # event == "end": this element and all its descendants are now
        # fully parsed -- safe to read its attrib/text and then clear it.
        my_id, has_children, _elem = stack.pop()
        tag = _strip_ns(elem.tag)
        properties: dict[str, object] = dict(elem.attrib)
        if not has_children:
            text = (elem.text or "").strip()
            if text:
                properties[RAW_PROP_TEXT] = text
        nodes[my_id - 1] = RawNode(id=my_id, tag=tag, properties=properties)
        elem.clear()
        if stack:
            # Detach the now-empty child shell from its parent so the
            # parent doesn't keep accumulating references to every sibling
            # it's already finished with.
            stack[-1][2].remove(elem)
        finished += 1
        if finished % _PROGRESS_LOG_INTERVAL == 0:
            logger.info(
                "project_xml_to_raw_graph: %d element(s) processed, %.1fs elapsed",
                finished, time.monotonic() - start,
            )
            if should_stop is not None and should_stop():
                logger.warning("project_xml_to_raw_graph: cancelled after %d element(s)", finished)
                raven_log("WARN", "P3", "ingest.raw_graph.project_cancelled projection parse stopped by cancel",
                          error_code="ARYX_ING_CANCELLED",
                          context={"elements_processed": finished, "result": "cancelled",
                                   "exit_condition": "cancelled"})
                raise PipelineCancelled(f"job cancelled during XML projection after {finished} element(s)")

    if finished >= _PROGRESS_LOG_INTERVAL:
        logger.info(
            "project_xml_to_raw_graph: done, %d node(s) / %d edge(s), %.1fs elapsed",
            len(nodes), len(edges), time.monotonic() - start,
        )
    raven_log("DEBUG", "P4", "ingest.raw_graph.project xml walked into nodes and edges",
              context={"nodes": len(nodes), "edges": len(edges),
                       "root_tag": nodes[0].tag if nodes else "", "bytes": len(data)})
    return RawGraphProjection(nodes=nodes, edges=edges)  # type: ignore[arg-type]  # every slot is filled by this point


def count_raw_graph_elements(
    data: bytes, should_stop: Callable[[], bool] | None = None,
) -> tuple[int, int]:
    """Count the (node, edge) totals ``project_xml_to_raw_graph`` would
    produce, without materializing a single ``RawNode``/``RawEdge``.

    Built for the Documents-tab discovery preview (PR #426 review:
    ``preview_raw_graph_counts`` only ever used ``len(nodes)``/``len(edges)``
    from the full projection, yet still paid its full memory cost -- a
    5.85M-node live upload held 5.85M ``RawNode`` objects just to report two
    integers). This walks the same ``iterparse`` events but keeps only a
    stack of currently-open elements (for parent/child edge counting and the
    same clear()+detach pattern as the full projection, to avoid the DOM
    re-accumulating under an uncleared root), so peak memory is O(nesting
    depth) instead of O(element count).

    should_stop: optional cancellation poll, checked at the same cadence as
    the progress log below -- the full projection has no cancellation
    support either, and a 240MB file's count-only pass is ~40-78s, but there
    is no reason a multi-GB file's count should be uninterruptible just
    because this is "only a preview."

    Returns:
        (node_count, edge_count) -- identical to
        ``len(projection.nodes), len(projection.edges)`` for the same bytes.
    """
    node_count = 0
    edge_count = 0
    stack: list[Element] = []
    finished = 0
    start = time.monotonic()
    for event, elem in defused_ET.iterparse(io.BytesIO(data), events=("start", "end")):
        if event == "start":
            node_count += 1
            if stack:
                edge_count += 1
            stack.append(elem)
            continue
        elem.clear()
        stack.pop()
        if stack:
            stack[-1].remove(elem)
        finished += 1
        if finished % _PROGRESS_LOG_INTERVAL == 0:
            logger.info(
                "count_raw_graph_elements: %d element(s) processed, %.1fs elapsed",
                finished, time.monotonic() - start,
            )
            if should_stop is not None and should_stop():
                logger.warning("count_raw_graph_elements: cancelled after %d element(s)", finished)
                raven_log("WARN", "P3", "ingest.raw_graph.count_cancelled preview count stopped by cancel",
                          error_code="ARYX_ING_CANCELLED",
                          context={"nodes_so_far": node_count, "edges_so_far": edge_count,
                                   "result": "partial", "exit_condition": "cancelled"})
                break
    if finished >= _PROGRESS_LOG_INTERVAL:
        logger.info(
            "count_raw_graph_elements: done, %d node(s) / %d edge(s), %.1fs elapsed",
            node_count, edge_count, time.monotonic() - start,
        )
    return node_count, edge_count
