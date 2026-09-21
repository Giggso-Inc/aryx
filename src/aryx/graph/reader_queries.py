"""Pure, patch-free GraphReader query implementations.

Split out of `graph/reader.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). Every function here takes GraphReader's bound `_query` method
(and, where relevant, an already-resolved `capped`/`skip` value) instead of
`self` — none of them call `get_settings()` or `FalkorDB` directly, so no
whitebox patch needed retargeting to move them out of `reader.py`.
GraphReader keeps a thin one-line delegating method for each.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from aryx.graph.reader_entity import _entity

_Query = Callable[..., list[list[Any]]]


def _get_entity(query: _Query, entity_id: int) -> dict[str, Any] | None:
    """Return a single entity's id/type/name/attributes, or None if absent."""
    rows = query(
        "MATCH (e:Entity {id: $id}) RETURN e.id, e.type, e.name, properties(e)",
        {"id": entity_id},
    )
    return _entity(rows[0]) if rows else None


def _distinct_types(query: _Query) -> list[str]:
    """Every distinct entity type in the graph — deterministic, no sampling.

    Callers that need "entities of a type matching X" must discover the
    type name here first, then find_entities(ontology_type=...). Sampling
    find_entities(limit=N) instead silently misses types on large graphs
    (a 46k-entity workspace can return a 1000-row page containing only
    2-3 dominant types).
    """
    rows = query("MATCH (e:Entity) RETURN DISTINCT e.type ORDER BY e.type")
    return [r[0] for r in rows if r[0]]


def _describe_schema(query: _Query, types: list[str], sample_per_type: int) -> dict[str, Any]:
    """Describe the graph schema as it actually exists, for query generation.

    The instance data uses generic ``:Entity`` nodes (ontology type in the
    ``type`` property and as an extra label) connected by ``:REL`` edges
    whose semantic name lives in the ``name`` property. Cypher written
    against the theoretical ontology (semantic edge types, no ``type``
    filter) returns nothing — callers generating queries must use this
    description instead.

    Returns:
        node_pattern / edge_pattern: canonical MATCH fragments.
        entity_types: every distinct ``type`` value.
        relationship_names: every distinct ``r.name`` value.
        properties_by_type: observed native property names per type
            (sampled, so rarely-populated properties may be missing).
    """
    rel_rows = query(
        "MATCH ()-[r:REL]->() RETURN DISTINCT r.name ORDER BY r.name")
    rel_names = [r[0] for r in rel_rows if r[0]]
    props_by_type: dict[str, list[str]] = {}
    for t in types:
        rows = query(
            "MATCH (e:Entity {type: $type}) RETURN properties(e) "
            f"LIMIT {max(1, int(sample_per_type))}",
            {"type": t},
        )
        keys: set[str] = set()
        for r in rows:
            if isinstance(r[0], dict):
                keys.update(r[0].keys())
        props_by_type[t] = sorted(keys)
    return {
        "node_pattern": "(e:Entity {type: $ontology_type})",
        "edge_pattern": "(a:Entity)-[r:REL {name: $relationship_name}]->(b:Entity)",
        "entity_types": types,
        "relationship_names": rel_names,
        "properties_by_type": props_by_type,
    }


def _find_entities(
    query: _Query, ontology_type: str | None, name: str | None,
    capped: int, skip: int, attrs: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Find entities filtered by type, name, and/or attribute-value predicates.

    `capped`/`skip` are resolved by the caller (GraphReader.find_entities),
    since capping reads `get_settings().graph_query_limit` — kept in
    reader.py so existing `aryx.graph.reader.get_settings` patches keep
    intercepting it.

    `attrs` — {attribute_key: value} predicates, ANDed together with
    everything else. Each value is matched case-insensitively against the
    node property's string form (mirrors `name`'s own CONTAINS-on-lowered-
    string approach, not exact-typed equality, since node property types
    are whatever the ingest pipeline happened to store). Keys are validated
    against ^[A-Za-z_][A-Za-z0-9_]*$ and rejected otherwise — Cypher
    property names cannot be parameterized the way values can, so an
    unvalidated key would be a straight injection path.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if ontology_type:
        clauses.append("e.type = $type")
        params["type"] = ontology_type
    if name:
        clauses.append("toLower(e.name) CONTAINS toLower($name)")
        params["name"] = name
    if attrs:
        for i, (key, value) in enumerate(attrs.items()):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"find_entities: invalid attribute key {key!r}")
            pname = f"attr_val_{i}"
            clauses.append(
                f"toLower(toString(e.{key})) CONTAINS toLower(toString(${pname}))"
            )
            params[pname] = value
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    rows = query(
        f"MATCH (e:Entity) {where}RETURN e.id, e.type, e.name, properties(e) "
        # ORDER BY is required for SKIP/LIMIT to paginate correctly —
        # Cypher/FalkorDB does not guarantee row order across separate
        # calls without an explicit sort key, so pagination without it
        # can return the same row twice (harmless) or silently skip
        # rows between pages (reintroduces the exact truncation bug
        # this offset param exists to fix). Matches oracle_graph_
        # reader.py's ORDER BY entity_id for the same reason.
        f"ORDER BY e.id SKIP {skip} LIMIT {capped}",
        params,
    )
    return [_entity(r) for r in rows]


def _neighbors(query: _Query, entity_id: int) -> list[dict[str, Any]]:
    """Return one-hop related entities in both directions.

    Each result carries the edge name, its direction ('out' or 'in')
    relative to the queried entity, and the connected entity's fields.
    """
    rows = query(
        "MATCH (e:Entity {id: $id})-[r:REL]->(n:Entity) "
        "RETURN n.id AS id, n.type AS type, n.name AS name, properties(n) AS attrs, "
        "r.name AS rel, 'out' AS dir "
        "UNION "
        "MATCH (e:Entity {id: $id})<-[r:REL]-(n:Entity) "
        "RETURN n.id AS id, n.type AS type, n.name AS name, properties(n) AS attrs, "
        "r.name AS rel, 'in' AS dir",
        {"id": entity_id},
    )
    return [{**_entity(r[:4]), "relationship": r[4], "direction": r[5]} for r in rows]


def _neighbors_batch(query: _Query, entity_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Batch one-hop neighbor lookup for multiple entities in one Cypher round-trip.

    Mirrors OracleGraphReader.neighbors_batch — same signature and return
    shape so CpqEngine.load_product_config can call it without branching on
    backend. FalkorDB round-trips are cheap (in-process), but a single
    UNWIND-based query still collapses N calls into 1 for callers scaling
    with entity count.
    """
    if not entity_ids:
        return {}
    rows = query(
        "UNWIND $ids AS eid "
        "MATCH (e:Entity {id: eid})-[r:REL]->(n:Entity) "
        "RETURN eid AS src, n.id AS id, n.type AS type, n.name AS name, properties(n) AS attrs, "
        "r.name AS rel, 'out' AS dir "
        "UNION "
        "UNWIND $ids AS eid "
        "MATCH (e:Entity {id: eid})<-[r:REL]-(n:Entity) "
        "RETURN eid AS src, n.id AS id, n.type AS type, n.name AS name, properties(n) AS attrs, "
        "r.name AS rel, 'in' AS dir",
        {"ids": list(entity_ids)},
    )
    result: dict[int, list[dict[str, Any]]] = {eid: [] for eid in entity_ids}
    for r in rows:
        src, rest = r[0], r[1:]
        result.setdefault(int(src), []).append(
            {**_entity(rest[:4]), "relationship": rest[4], "direction": rest[5]}
        )
    return result


def _all_relationships(query: _Query, limit: int | None) -> list[dict[str, Any]]:
    """Return relationship edges in the graph, optionally capped."""
    cap = f" LIMIT {max(1, int(limit))}" if limit else ""
    rows = query(
        f"MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN a.id, b.id, r.name{cap}"
    )
    return [{"source": r[0], "target": r[1], "name": r[2]} for r in rows]


def _provenance(query: _Query, entity_id: int) -> list[dict[str, Any]]:
    """Return the source records an entity was projected from."""
    rows = query(
        "MATCH (e:Entity {id: $id})-[:FROM]->(s:Source) "
        "RETURN s.system, s.dataset, s.record_id",
        {"id": entity_id},
    )
    return [{"system": r[0], "dataset": r[1], "record_id": r[2]} for r in rows]


def _shortest_path(query: _Query, src: int, dst: int, max_hops: int) -> list[dict[str, Any]]:
    """Return the shortest path between two entities (either direction), or []."""
    hops = max(1, min(int(max_hops), 10))
    # FalkorDB rejects undirected shortestPath, so try outbound then inbound
    # and keep whichever is shorter.
    candidates: list[tuple[list, list]] = []
    for arrow_a, arrow_b in (("-", "->"), ("<-", "-")):
        rows = query(
            "MATCH (a:Entity {id: $a}), (b:Entity {id: $b}) "
            f"WITH shortestPath((a){arrow_a}[:REL*1..{hops}]{arrow_b}(b)) AS p "
            "WHERE p IS NOT NULL "
            "RETURN [n IN nodes(p) | [n.id, n.type, n.name, properties(n)]] AS ns, "
            "[r IN relationships(p) | r.name] AS rs",
            {"a": src, "b": dst},
        )
        if rows:
            candidates.append((rows[0][0], rows[0][1]))
    if not candidates:
        return []
    nodes, rels = min(candidates, key=lambda c: len(c[0]))
    steps: list[dict[str, Any]] = []
    for i, n in enumerate(nodes):
        steps.append({**_entity(n), "relationship": rels[i - 1] if i > 0 else None})
    return steps
