"""Oracle Property Graph reader — queries ADB 23ai backing tables with SQL/PGQ."""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings

logger = logging.getLogger(__name__)


class OracleGraphReader:
    """Reads entities, relationships, and provenance from Oracle ADB 23ai backing tables."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        """Connect to Oracle ADB and scope all reads to workspace_id."""
        from aryx.store.oracle_pool import get_oracle_pool
        self._pool = get_oracle_pool(dsn)
        self._workspace_id = workspace_id

    def get_entity(self, entity_id: int) -> dict[str, Any] | None:
        """Return {id, type, name} for one entity, or None if not in this workspace."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT entity_id, type, name FROM aryx_graph_vertex "
                    "WHERE workspace_id = :1 AND entity_id = :2",
                    (self._workspace_id, entity_id),
                )
                row = cur.fetchone()
        return {"id": row[0], "type": row[1], "name": row[2]} if row else None

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

    def find_entities(self, ontology_type: str | None = None,
                      name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Find entities filtered by type and/or case-insensitive name substring."""
        capped = max(1, min(int(limit), get_settings().graph_query_limit))
        clauses = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": self._workspace_id}
        if ontology_type:
            clauses.append("type = :typ")
            params["typ"] = ontology_type
        if name:
            clauses.append("LOWER(name) LIKE '%' || LOWER(:name) || '%'")
            params["name"] = name
        where = " AND ".join(clauses)
        # FETCH FIRST does not accept a bind variable in all Oracle versions —
        # inline the capped integer (already validated, no injection risk).
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT entity_id, type, name FROM aryx_graph_vertex "
                    f"WHERE {where} FETCH FIRST {capped} ROWS ONLY",  # nosec S608 — capped is a validated int
                    params,
                )
                rows = cur.fetchall()
        return [{"id": r[0], "type": r[1], "name": r[2]} for r in rows]

    def neighbors(self, entity_id: int) -> list[dict[str, Any]]:
        """Return one-hop related entities in both directions with relationship name and direction."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT v.entity_id, v.type, v.name, e.name AS rel, 'out' AS dir
                      FROM aryx_graph_edge e
                      JOIN aryx_graph_vertex v
                        ON v.workspace_id = e.workspace_id AND v.entity_id = e.tgt_id
                     WHERE e.workspace_id = :ws AND e.src_id = :eid
                    UNION ALL
                    SELECT v.entity_id, v.type, v.name, e.name AS rel, 'in' AS dir
                      FROM aryx_graph_edge e
                      JOIN aryx_graph_vertex v
                        ON v.workspace_id = e.workspace_id AND v.entity_id = e.src_id
                     WHERE e.workspace_id = :ws AND e.tgt_id = :eid
                    """,
                    {"ws": self._workspace_id, "eid": entity_id},
                )
                rows = cur.fetchall()
        return [{"id": r[0], "type": r[1], "name": r[2],
                 "relationship": r[3], "direction": r[4]} for r in rows]

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
        """Return the source records (system, dataset, record_id) an entity was projected from."""
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
                            SELECT e.src_id, v1.type, v1.name,
                                   e.tgt_id, v2.type, v2.name,
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
                            aid, atype, aname, bid, btype, bname, rname = row
                            entity_map[aid] = {"id": aid, "type": atype, "name": aname}
                            entity_map[bid] = {"id": bid, "type": btype, "name": bname}
                            rels.append({"source": aid, "target": bid, "name": rname})

        # 3. Fill remaining slots with isolated entities
        remaining = capped - len(entity_map)
        if remaining > 0:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT entity_id, type, name FROM aryx_graph_vertex "
                        f"WHERE workspace_id = :1 FETCH FIRST {remaining} ROWS ONLY",  # nosec S608
                        (self._workspace_id,),
                    )
                    for row in cur.fetchall():
                        eid, etype, ename = row
                        if eid not in entity_map:
                            entity_map[eid] = {"id": eid, "type": etype, "name": ename}

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
            # Reconstruct ordered path: first node + (rel, next_node) per step
            steps: list[dict[str, Any]] = []
            for i, (v1_id, rel_name, v2_id) in enumerate(step_rows):
                if i == 0:
                    first = self.get_entity(int(v1_id)) or {"id": int(v1_id), "type": None, "name": None}
                    steps.append({**first, "relationship": None})
                nxt = self.get_entity(int(v2_id)) or {"id": int(v2_id), "type": None, "name": None}
                steps.append({**nxt, "relationship": rel_name})
            return steps
        except Exception:
            logger.warning("shortest_path SQL/PGQ failed; falling back to empty", exc_info=True)
            return []
