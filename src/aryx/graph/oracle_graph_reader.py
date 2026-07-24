"""Oracle Property Graph reader — queries ADB 23ai backing tables with SQL/PGQ."""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.config import get_settings

logger = logging.getLogger(__name__)


def _parse_attrs(raw: Any) -> dict[str, Any]:
    """Best-effort decode of the stored attributes column.

    python-oracledb can return a native JSON column as an already-parsed
    dict or as a string depending on driver/version — handle both rather
    than assume.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _entity(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map an (entity_id, type, name[, attributes]) row to an entity dict."""
    entity: dict[str, Any] = {"id": row[0], "type": row[1], "name": row[2]}
    if len(row) > 3:
        entity["attributes"] = _parse_attrs(row[3])
    return entity


class OracleGraphReader:
    """Reads entities, relationships, and provenance from Oracle ADB 23ai backing tables."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        """Connect to Oracle ADB and scope all reads to workspace_id."""
        from aryx.store.oracle_pool import get_oracle_pool
        self._pool = get_oracle_pool(dsn)
        self._workspace_id = workspace_id

    def get_entity(self, entity_id: int) -> dict[str, Any] | None:
        """Return {id, type, name, attributes} for one entity, or None if not in this workspace."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT entity_id, type, name, attributes FROM aryx_graph_vertex "
                    "WHERE workspace_id = :1 AND entity_id = :2",
                    (self._workspace_id, entity_id),
                )
                row = cur.fetchone()
        return _entity(row) if row else None

    def distinct_types(self) -> list[str]:
        """Every distinct entity type in this workspace — deterministic, no sampling."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT type FROM aryx_graph_vertex "
                    "WHERE workspace_id = :1 ORDER BY type",
                    (self._workspace_id,),
                )
                return [r[0] for r in cur.fetchall() if r[0]]

    def describe_schema(self, sample_per_type: int = 25) -> dict[str, Any]:
        """Describe the actual stored schema for query generation (port parity).

        Mirrors GraphReader.describe_schema: entity types, relationship names,
        and observed attribute keys per type (sampled from the JSON column).
        """
        types = self.distinct_types()
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT name FROM aryx_graph_edge "
                    "WHERE workspace_id = :1 ORDER BY name",
                    (self._workspace_id,),
                )
                rel_names = [r[0] for r in cur.fetchall() if r[0]]
                props_by_type: dict[str, list[str]] = {}
                for t in types:
                    cur.execute(
                        "SELECT attributes FROM aryx_graph_vertex "
                        "WHERE workspace_id = :1 AND type = :2 "
                        "FETCH FIRST :3 ROWS ONLY",
                        (self._workspace_id, t, max(1, int(sample_per_type))),
                    )
                    keys: set[str] = set()
                    for (raw,) in cur.fetchall():
                        keys.update(_parse_attrs(raw).keys())
                    props_by_type[t] = sorted(keys)
        return {
            "node_pattern": "(e:Entity {type: $ontology_type})",
            "edge_pattern": "(a:Entity)-[r:REL {name: $relationship_name}]->(b:Entity)",
            "entity_types": types,
            "relationship_names": rel_names,
            "properties_by_type": props_by_type,
        }

    def find_entities(self, ontology_type: str | None = None,
                      name: str | None = None, limit: int = 50,
                      offset: int = 0) -> list[dict[str, Any]]:
        """Find entities filtered by type and/or case-insensitive name substring.

        Args:
            ontology_type: Exact ontology type to match, or None for any.
            name: Substring matched case-insensitively against the name, or None.
            limit: Maximum rows to return (coerced to int, capped at ARYX_GRAPH_QUERY_LIMIT).
            offset: Rows to skip before applying limit — see GraphReader.find_entities.

        Returns:
            A list of {id, type, name, attributes} dicts.
        """
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if ontology_type:
            clauses.append("e.type = $type")
            params["typ"] = ontology_type
        if name:
            clauses.append("LOWER(name) LIKE '%' || LOWER(:name) || '%'")
            params["name"] = name
        where = " AND ".join(clauses)
        capped = max(1, min(int(limit), get_settings().graph_query_limit))
        skip = max(0, int(offset))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT entity_id, type, name, attributes FROM aryx_graph_vertex "
                    f"WHERE {where} ORDER BY entity_id "
                    f"OFFSET {skip} ROWS FETCH NEXT {capped} ROWS ONLY",  # nosec S608 — capped/skip are validated ints
                    params,
                )
                rows = cur.fetchall()
        return [_entity(r) for r in rows]

    def neighbors(self, entity_id: int) -> list[dict[str, Any]]:
        """Return one-hop related entities in both directions with relationship name and direction."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT v.entity_id, v.type, v.name, v.attributes, e.name AS rel, 'out' AS dir
                      FROM aryx_graph_edge e
                      JOIN aryx_graph_vertex v
                        ON v.workspace_id = e.workspace_id AND v.entity_id = e.tgt_id
                     WHERE e.workspace_id = :ws AND e.src_id = :eid
                    UNION ALL
                    SELECT v.entity_id, v.type, v.name, v.attributes, e.name AS rel, 'in' AS dir
                      FROM aryx_graph_edge e
                      JOIN aryx_graph_vertex v
                        ON v.workspace_id = e.workspace_id AND v.entity_id = e.src_id
                     WHERE e.workspace_id = :ws AND e.tgt_id = :eid
                    """,
                    {"ws": self._workspace_id, "eid": entity_id},
                )
                rows = cur.fetchall()
        return [{**_entity(r[:4]), "relationship": r[4], "direction": r[5]} for r in rows]

    def all_relationships(self) -> list[dict[str, Any]]:
        """Return every relationship edge in this workspace as {source, target, name}."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT src_id, tgt_id, name FROM aryx_graph_edge "
                    "WHERE workspace_id = :1",
                    (self._workspace_id,),
                )
                rows = cur.fetchall()
        return [{"source": r[0], "target": r[1], "name": r[2]} for r in rows]

    def provenance(self, entity_id: int) -> list[dict[str, Any]]:
        """Return the source records an entity was projected from."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.system, s.dataset, s.record_id
                      FROM aryx_graph_provenance p
                      JOIN aryx_graph_source s
                        ON s.workspace_id = p.workspace_id AND s.source_id = p.source_id
                     WHERE p.workspace_id = :1 AND p.entity_id = :2
                    """,
                    (self._workspace_id, entity_id),
                )
                rows = cur.fetchall()
        return [{"system": r[0], "dataset": r[1], "record_id": r[2]} for r in rows]

    def subgraph(self, rel_limit: int = 500) -> dict[str, Any]:
        """Return a connected subgraph for graph-canvas rendering.

        Mirrors FalkorReader.subgraph(): samples proportionally from every
        relationship type then fills remaining slots with isolated entities.
        """
        capped = max(1, min(int(rel_limit), get_settings().graph_query_limit))
        entity_map: dict[int, dict[str, Any]] = {}
        rels: list[dict[str, Any]] = []

        # 1. Distinct relationship types in this workspace
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT name FROM aryx_graph_edge WHERE workspace_id = :1",
                    (self._workspace_id,),
                )
                rel_types = [r[0] for r in cur.fetchall() if r[0]]

        # 2. Sample edges proportionally per type
        if rel_types:
            per_type = max(1, capped // len(rel_types))
            for rtype in rel_types:
                with self._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT e.src_id, v1.type, v1.name, v1.attributes,
                                   e.tgt_id, v2.type, v2.name, v2.attributes,
                                   e.name
                              FROM aryx_graph_edge e
                              JOIN aryx_graph_vertex v1
                                ON v1.workspace_id = e.workspace_id
                               AND v1.entity_id = e.src_id
                              JOIN aryx_graph_vertex v2
                                ON v2.workspace_id = e.workspace_id
                               AND v2.entity_id = e.tgt_id
                             WHERE e.workspace_id = :ws AND e.name = :rel
                             FETCH FIRST {per_type} ROWS ONLY
                            """,  # nosec S608 — per_type is a validated int
                            {"ws": self._workspace_id, "rel": rtype},
                        )
                        for row in cur.fetchall():
                            aid, atype, aname, aattrs, bid, btype, bname, battrs, rname = row
                            entity_map[aid] = _entity((aid, atype, aname, aattrs))
                            entity_map[bid] = _entity((bid, btype, bname, battrs))
                            rels.append({"source": aid, "target": bid, "name": rname})

        # 3. Fill remaining slots with isolated entities
        remaining = capped - len(entity_map)
        if remaining > 0:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT entity_id, type, name, attributes FROM aryx_graph_vertex "
                        f"WHERE workspace_id = :1 FETCH FIRST {remaining} ROWS ONLY",  # nosec S608
                        (self._workspace_id,),
                    )
                    for row in cur.fetchall():
                        if row[0] not in entity_map:
                            entity_map[row[0]] = _entity(row)

        return {"entities": list(entity_map.values()), "relationships": rels}

    def shortest_path(self, src: int, dst: int, max_hops: int = 6) -> list[dict[str, Any]]:
        """Return shortest path using Oracle 23ai SQL/PGQ GRAPH_TABLE ONE ROW PER STEP.

        ONE ROW PER STEP (v1, e, v2) returns one row per edge in the path, each
        carrying (left_vertex, edge, right_vertex) properties. We collect all steps
        then resolve entity details for each unique vertex.
        """
        hops = max(1, min(int(max_hops), 10))
        # ONE ROW PER STEP is the correct Oracle 23ai syntax for path traversal.
        # LISTAGG inside COLUMNS is not valid in GRAPH_TABLE context.
        sql = f"""
            SELECT v1_id, rel_name, v2_id
              FROM GRAPH_TABLE (
                aryx_knowledge_graph
                MATCH SHORTEST (
                  (a IS aryx_graph_vertex WHERE a.entity_id = :src)
                  -[r IS aryx_graph_edge]->{{1,{hops}}}  # nosec S608 — hops is a validated int
                  (b IS aryx_graph_vertex WHERE b.entity_id = :dst)
                )
                ONE ROW PER STEP (a, r, b)
                COLUMNS (
                  a.entity_id AS v1_id,
                  r.name      AS rel_name,
                  b.entity_id AS v2_id
                )
              )
        """
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, {"src": src, "dst": dst})
                    step_rows = cur.fetchall()
            if not step_rows:
                return []
            # Reconstruct ordered path: first node + (rel, next_node) per step.
            # get_entity() already includes attributes; the fallback dict for a
            # vertex missing from this workspace matches that same shape.
            steps: list[dict[str, Any]] = []
            for i, (v1_id, rel_name, v2_id) in enumerate(step_rows):
                if i == 0:
                    first = self.get_entity(int(v1_id)) or \
                        {"id": int(v1_id), "type": None, "name": None, "attributes": {}}
                    steps.append({**first, "relationship": None})
                nxt = self.get_entity(int(v2_id)) or \
                    {"id": int(v2_id), "type": None, "name": None, "attributes": {}}
                steps.append({**nxt, "relationship": rel_name})
            return steps
        except Exception:
            logger.warning("shortest_path SQL/PGQ failed; falling back to empty", exc_info=True)
            return []
