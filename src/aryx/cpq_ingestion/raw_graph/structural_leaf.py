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
    allowed = {RAW_PROP_TEXT, *_carried_keys()}
    for n in nodes:
        if set(n.properties) - allowed:
            return False
    return node_ids.isdisjoint(parent_ids)


_BML_KEYS: tuple[str, ...] | None = None    # (tables, queries, query_tables, script_props); cached on success only


def _bml_keys() -> tuple[str, ...]:
    """The CSV BML property names, or () when that module cannot be imported (a failure is not cached).

    Imported lazily (csv_bml_ingestion imports this package). The fold must never fail, or stay disabled for
    the life of the process, because an optional enrichment module could not load once.
    """
    global _BML_KEYS
    if _BML_KEYS is not None:
        return _BML_KEYS
    try:
        from aryx.csv_bml_ingestion.bml_graph import (  # noqa: PLC0415
            QUERIES_KEY, QUERY_TABLES_KEY, SCRIPT_PROPS_KEY, TABLES_KEY,
        )
    except ImportError:
        logger.warning("structural leaf fold: csv_bml_ingestion unavailable; BML lists will not be carried",
                       exc_info=True)
        return ()
    _BML_KEYS = (TABLES_KEY, QUERIES_KEY, QUERY_TABLES_KEY, SCRIPT_PROPS_KEY)
    return _BML_KEYS


def _carried_keys() -> tuple[str, ...]:
    """Query-table lists the CSV BML enrichment adds to a node that holds SQL (not XML attributes).

    They do not make a tag a non-leaf: the fold carries them onto the parent with the text.
    """
    return _bml_keys()[:3]


def _carry_lists(parent: RawNode, leaf: RawNode, tag: str) -> None:
    """Merge the leaf's query-table lists onto the parent (extend; never nest; tables de-duplicated).

    Also records the tag the script was folded under (`bml_script_props`), so a CSV BML match can name the
    property that holds the script body instead of guessing it.
    """
    keys = _bml_keys()
    if not keys:
        return
    tables_key, queries_key, query_tables_key, script_props_key = keys
    carried = False
    for key in (tables_key, queries_key, query_tables_key):
        values = leaf.properties.get(key)
        if not isinstance(values, list):
            continue
        carried = True
        current = parent.properties.get(key)
        if not isinstance(current, list):
            parent.properties[key] = list(values)
        elif key == tables_key:
            current.extend(v for v in values if v not in current)
        else:
            current.extend(values)      # queries and their tables stay parallel
    if carried:
        tags = parent.properties.setdefault(script_props_key, [])
        if isinstance(tags, list) and tag not in tags:
            tags.append(tag)


def fold_structural_leaf_tags(
    edges: list[RawEdge],
    by_tag: dict[str, list[RawNode]],
    *, log_id: str | None = None, source_key: str = "",
    parent_ids: set[int] | None = None,
) -> dict[str, list[RawNode]]:
    """Fold every structural-leaf tag's value onto its parent, drop it from by_tag.

    `parent_ids` -- optional precomputed set of every node id that is the source of an edge, so a
    caller that also needs it (the post-fold audit) builds it once for the whole file.

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

    Performance (PR review M4, then N2 round 2, 2026-10-04): classification
    needs only ``parent_ids`` (which node ids have at least one child) --
    built in ONE pass over ``edges`` regardless of outcome, since every
    candidate tag must be classified either way. ``parent_of`` (the
    child-id -> parent-id map folding actually needs) is NOT built in that
    same pass -- M4's first fix still built it unconditionally alongside
    ``parent_ids`` even though most files fold nothing, and even when
    something does fold, only the leaf tags' own nodes ever need a parent
    lookup, not every node in the file. ``parent_of`` is now built in a
    second pass, only when ``leaf_tags`` is non-empty, and restricted to
    edges whose target is one of the leaf tags' own node ids -- a dict
    sized to the leaf tags' node count, not the whole file's edge count
    (e.g. one 439,946-node leaf tag out of 5.85M total edges is ~13x
    smaller than the unconditional version). ``nodes_by_id`` is likewise
    only built if at least one tag actually classifies as a leaf, and
    restricted to the distinct parent ids ``parent_of`` actually
    references -- not every node in the file (which would also include
    every other tag's nodes, the leaf nodes themselves, and any node
    that's nobody's parent).

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

    if parent_ids is None:
        parent_ids = {edge.source_id for edge in edges}

    leaf_tags = {
        tag: nodes for tag, nodes in by_tag.items()
        if is_structural_leaf_tag(nodes, parent_ids)
    }
    if not leaf_tags:
        return by_tag

    leaf_node_ids: set[int] = {n.id for nodes in leaf_tags.values() for n in nodes}
    parent_of: dict[int, int] = {
        edge.target_id: edge.source_id for edge in edges
        if edge.target_id in leaf_node_ids
    }

    # nodes_by_id only ever needs to answer "what node is THIS parent id" --
    # restricting it to the distinct parent ids actually referenced (not
    # every node in the file, which includes every other tag's nodes, the
    # leaf nodes themselves, and any node that's nobody's parent) shrinks it
    # to the number of unique parents being folded onto, not the file size.
    needed_parent_ids: set[int] = set(parent_of.values())
    nodes_by_id: dict[int, RawNode] = {
        n.id: n for nodes in by_tag.values() for n in nodes
        if n.id in needed_parent_ids
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
            _carry_lists(parent, leaf, tag)
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
