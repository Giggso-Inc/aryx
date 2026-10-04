"""Structural-leaf tag classification and folding (§1 Tier 1, 2026-10-04).

A structural leaf is an XML tag whose every occurrence is a plain scalar
value holder -- no real XML attributes, no children -- e.g. a repeated
``<id>123</id>`` under every parent record. Landing and resolving hundreds
of thousands of these as their own dataset is pure waste: the value is
really just a property of its parent element, not an independent entity.
This module detects that shape and folds the value onto the parent's
``RawNode.properties`` instead, so ``resolve_and_relate_raw_graph()`` never
lands or resolves that tag at all -- O(1) relative to tag volume, not
O(record count), because the work is never done.

See docs/ingestion/CPQ_XML_CONFIRM_RESOLVE_PERFORMANCE_ISSUES_2026-10-04.md
§1 Tier 1 for the full investigation this was built from.
"""
from __future__ import annotations

import logging

from aryx.cpq_ingestion.constants import RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawNode
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


def is_structural_leaf_tag(nodes: list[RawNode], parent_ids: set[int]) -> bool:
    """True if every node of this tag has no real attributes and no children.

    A leaf's own text value is stored under ``RAW_PROP_TEXT`` by
    ``project_xml_to_raw_graph`` even when the element has zero real XML
    attributes (see ``xml_projector.py``'s "end" branch) -- so
    ``properties`` is never actually empty for a true scalar leaf, and a
    naive ``not any(n.properties ...)`` check would never fire. Real
    attributes are anything in ``properties`` other than ``RAW_PROP_TEXT``.

    ``parent_ids``: the set of every node id that is the SOURCE of at least
    one edge (i.e. has at least one child), precomputed ONCE by the caller
    from the whole projection's edges. Taking this instead of the full
    ``RawGraphProjection`` is the PR review M4 fix: the original version
    rebuilt ``{e.source_id for e in projection.edges if e.source_id in
    node_ids}`` from scratch for every candidate tag, which is O(tags x
    edges) -- about 5.85M edges scanned per candidate tag on the file this
    was built against. A single O(edges) pass up front, reused via a plain
    set-membership check per tag, removes that multiplier entirely.
    """
    node_ids = {n.id for n in nodes}
    for n in nodes:
        if set(n.properties) - {RAW_PROP_TEXT}:
            return False
    return node_ids.isdisjoint(parent_ids)


def fold_structural_leaf_tags(
    edges: list[RawEdge],
    by_tag: dict[str, list[RawNode]],
    *, log_id: str | None = None, source_key: str = "",
) -> dict[str, list[RawNode]]:
    """Fold every structural-leaf tag's value onto its parent, drop it from by_tag.

    Mutates the parent ``RawNode.properties`` dicts in place (``RawNode``
    is a frozen dataclass, but its ``properties`` dict is not -- mutating
    the dict's contents, not reassigning the field, is safe and is how
    every other property on a node is ever set). Returns a new dict with
    every folded tag removed, so the caller's per-tag resolve loop and its
    ``on_progress`` tag-count scaling both only ever see tags that still
    need resolving.

    A parent that already has a same-named property (two leaf children
    under one parent sharing a tag, or a real attribute with the same
    name) accumulates a list instead of being overwritten, so no leaf
    value is silently dropped. A leaf with no parent (an XML document's
    root tag classifying as a leaf, which would be unusual but not
    impossible) is left un-folded and un-removed, falling back to the
    normal resolve path for that tag -- folding onto nothing would lose
    the value outright, which is worse than the cost this fix saves. A
    leaf with no text at all (an empty marker element, e.g. ``<flag/>``)
    folds as an empty string rather than being silently skipped (PR review
    N2) -- skipping it entirely would otherwise still count the tag as
    "fully folded" (zero folds, zero orphans) and drop it from the resolve
    set with no record of it anywhere.

    Performance (PR review M4): the two full-projection structures this
    needs -- ``parent_ids`` (classification) and ``parent_of`` (folding) --
    are built together in ONE pass over ``edges`` regardless of outcome,
    since classifying every tag requires ``parent_ids`` anyway.
    ``nodes_by_id``, the expensive one (a dict of every node, same
    cardinality as the file -- 5.85M entries on the file this was built
    against), is only built if at least one tag actually classifies as a
    leaf, and never if ``by_tag`` has nothing foldable.

    Takes ``edges`` directly rather than a ``RawGraphProjection`` (§3b,
    2026-10-04) -- this function's only two uses of a projection were
    ``.edges`` and ``.nodes`` (the latter only to build ``nodes_by_id``,
    itself derivable from ``by_tag``'s own values, which together already
    contain every node). Decoupling from the projection type means the
    streaming `xml_bytes` path in ``resolve_and_relate_raw_graph()`` can
    call this unchanged, without ever constructing a separate
    whole-document node list just to satisfy this function's old
    signature.
    """
    if not by_tag:
        return by_tag

    parent_ids: set[int] = set()
    parent_of: dict[int, int] = {}
    for edge in edges:
        parent_ids.add(edge.source_id)
        parent_of[edge.target_id] = edge.source_id

    leaf_tags = {
        tag: nodes for tag, nodes in by_tag.items()
        if is_structural_leaf_tag(nodes, parent_ids)
    }
    if not leaf_tags:
        return by_tag

    nodes_by_id: dict[int, RawNode] = {
        n.id: n for nodes in by_tag.values() for n in nodes
    }

    folded_tags: list[str] = []
    result: dict[str, list[RawNode]] = {
        tag: nodes for tag, nodes in by_tag.items() if tag not in leaf_tags
    }
    for tag, nodes in leaf_tags.items():
        folded_count = 0
        orphan_count = 0
        for leaf in nodes:
            # None -> no text at all (an empty marker element) folds as ""
            # rather than being skipped -- see docstring, PR review N2.
            text = leaf.properties.get(RAW_PROP_TEXT, "")
            parent_id = parent_of.get(leaf.id)
            parent = nodes_by_id.get(parent_id) if parent_id is not None else None
            if parent is None:
                orphan_count += 1
                continue
            existing = parent.properties.get(tag)
            if existing is None:
                parent.properties[tag] = text
            elif isinstance(existing, list):
                existing.append(text)
            else:
                parent.properties[tag] = [existing, text]
            folded_count += 1
        if orphan_count:
            # Parentless leaves (e.g. a leaf-shaped root tag) keep this tag
            # in the resolve path so their values aren't silently lost.
            result[tag] = nodes
            logger.info(
                "structural leaf fold: tag=%s kept in resolve path, %d/%d node(s) had no "
                "parent to fold onto", tag, orphan_count, len(nodes),
            )
            continue
        folded_tags.append(tag)
        logger.info(
            "structural leaf fold: tag=%s folded %d node(s) onto their parents, "
            "removed from per-tag resolve", tag, folded_count,
        )
        raven_log(
            "INFO", "P4", "ingest.raw_graph.structural_leaf_folded tag folded onto parent, skipped resolve",
            context={
                "log_id": log_id, "source_key": source_key, "tag": tag,
                "nodes_folded": folded_count, "reason_code": "STRUCTURAL_LEAF_TAG",
                "selected_option": "fold", "available_options": ["fold", "resolve"],
            },
        )
    if folded_tags:
        raven_log(
            "INFO", "P4", "ingest.raw_graph.structural_leaf_summary structural leaf tags folded this file",
            context={
                "log_id": log_id, "source_key": source_key,
                "tags_folded": len(folded_tags), "tags_remaining": len(result),
                "folded_tag_names": folded_tags,
            },
        )
    return result
