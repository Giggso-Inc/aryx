"""Menu items sit one hop behind a ``Children`` wrapper node in a graph built from the raw XML.

The CPQ XML nests an attribute's menu items under the attribute, and the raw-graph pipeline keeps the nesting as
``attribute -> Children wrapper -> menu item`` (the wrapper type is ``<Prefix>Children`` or ``_children``). The engine
collects an attribute's options from its DIRECT neighbours of a menu-item type, so in such a workspace no attribute
had any option and every question came out as a free-text prompt.

``through_children_wrappers`` widens a neighbour map by one hop: each node also gets the neighbours of the wrappers
it contains (``direction == "out"``, never its parent's wrapper). A graph without wrappers is returned unchanged, so
the older path behaves exactly as before. Nothing here names an attribute, a menu or a catalog.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_BATCH = 400          # ids per neighbours_batch call (Oracle caps an IN list at 1000 and the query uses it twice)


def is_children_wrapper(neighbor: dict[str, Any]) -> bool:
    """A wrapper this node CONTAINS: type ends in ``children`` and the edge points away from the node."""
    kind = (neighbor.get("type") or "").lower().replace("_", "")
    return kind.endswith("children") and neighbor.get("direction") in (None, "out")


def through_children_wrappers(
    reader: Any, neighbors_by_id: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    """``neighbors_by_id`` plus, for every node, the neighbours behind the Children wrappers it contains.

    Best effort: if the second lookup fails the original map is returned, so options are never lost, only not widened.
    """
    wrappers = {eid: [n["id"] for n in found if is_children_wrapper(n)] for eid, found in neighbors_by_id.items()}
    wrapper_ids = sorted({w for ids in wrappers.values() for w in ids})
    if not wrapper_ids:
        return neighbors_by_id
    behind: dict[int, list[dict[str, Any]]] = {}
    try:
        for start in range(0, len(wrapper_ids), _BATCH):
            behind.update(reader.neighbors_batch(wrapper_ids[start:start + _BATCH]))
    except Exception:  # noqa: BLE001  e.g. a reader without neighbors_batch
        logger.debug("cpq: neighbours behind Children wrappers not available", exc_info=True)
        return neighbors_by_id
    widened: dict[int, list[dict[str, Any]]] = {}
    for eid, found in neighbors_by_id.items():
        extra = [m for w in wrappers.get(eid, ()) for m in behind.get(w, ())
                 if m.get("direction") in (None, "out") and m.get("id") != eid]
        widened[eid] = [*found, *extra] if extra else found
    return widened
