"""Rule-matching and graph-write primitives for the forward-chaining evaluator.

Split out of `reasoning/engine.py` (Raven Style Compliance Plan, Phase
2b, 2026-09-03). These functions only receive `graph`/`entity` as
parameters — they never call a module-level name themselves — so they
carry zero patch-retargeting risk even though `test_scalability_fixes.py`
patches `aryx.reasoning.engine.FalkorStore` in some of the same test
functions that call `_apply_edge` (that patch is for `evaluate_workspace`'s
own construction of a `FalkorStore`, not for anything `_apply_edge` itself
does — confirmed by reading the function body).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aryx.graph.falkor_store import FalkorStore

# Relationship names interpolated into Cypher must be safe identifiers.
_REL_NAME_RE = re.compile(r"^[A-Z0-9_]+$")

_OPS = {
    ">":  lambda a, b: float(a) > float(b),
    ">=": lambda a, b: float(a) >= float(b),
    "<":  lambda a, b: float(a) < float(b),
    "<=": lambda a, b: float(a) <= float(b),
    "==": lambda a, b: str(a) == str(b),
    "!=": lambda a, b: str(a) != str(b),
    "contains": lambda a, b: str(b).lower() in str(a or "").lower(),
}


def _match(entity: dict, when: dict) -> bool:
    """Test one entity against one when-clause."""
    if when.get("type") and entity.get("type") != when["type"]:
        return False
    attr = when.get("attr")
    if not attr:
        # type-only rule: SQL already filtered by type, no attribute condition
        return True
    op = _OPS.get(when.get("op", "=="))
    if op is None:
        return False
    val = (entity.get("attributes") or {}).get(attr)
    if val is None:
        return False
    try:
        return op(val, when.get("value"))
    except (TypeError, ValueError):
        return False


def _apply_label(graph: "FalkorStore", entity_id: int, label: str) -> None:
    """Write an inferred_label attribute on the entity in FalkorDB."""
    graph.run(
        "MATCH (n {id: $id}) SET n.inferred_label = $label",
        params={"id": int(entity_id), "label": str(label)},
    )


def _apply_edge(graph: "FalkorStore", source_id: int, name: str,
                target_type: str, target_name: str) -> None:
    """Create an INF_-prefixed edge to a target entity (matched by type+name)."""
    safe = name.upper()
    if not _REL_NAME_RE.match(safe):
        raise ValueError(
            f"Invalid relationship name {name!r}: must match [A-Z0-9_]+"
        )
    rel = f"INF_{safe}"
    graph.run(
        "MATCH (s {id: $sid}), (t {ontology_type: $ttype, name: $tname}) "
        f"MERGE (s)-[r:{rel} {{inferred: true}}]->(t)",
        params={"sid": int(source_id), "ttype": target_type,
                "tname": target_name},
    )


def _fire(graph: "FalkorStore", entity: dict, then: dict) -> int:
    """Apply the then-clause; return 1 on success, 0 on no-op."""
    eid = int(entity.get("id", 0))
    if not eid:
        return 0
    if "set_label" in then:
        _apply_label(graph, eid, str(then["set_label"]))
        return 1
    if "add_relationship" in then:
        _apply_edge(
            graph, eid, str(then["add_relationship"]),
            str(then.get("target_type", "")),
            str(then.get("target_name", "")),
        )
        return 1
    return 0
