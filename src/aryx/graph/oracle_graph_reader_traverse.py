"""Subgraph sampling + SQL/PGQ shortest-path traversal, mixed into
OracleGraphReader.

Split out of `graph/oracle_graph_reader.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). `shortest_path` is exercised directly by
`tests/test_oracle_graph_reader_shortest_path_scope.py` via the real
`OracleGraphReader` class (no patches) — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.config import get_settings
from aryx.graph.oracle_graph_reader_helpers import _entity

logger = logging.getLogger(__name__)


class _OracleGraphTraverseMixin:
    """subgraph / shortest_path, mixed into OracleGraphReader."""

    def subgraph(self, rel_limit: int = 500) -> dict[str, Any]:
        """Return a connected subgraph for graph-canvas rendering.

        Mirrors FalkorReader.subgraph(): samples proportionally from every
        relationship type then fills remaining slots with isolated entities.
        """
        capped = max(1, min(int(rel_limit), get_settings().graph_query_limit))
        entity_map: dict[int, dict[str, Any]] = {}
        rels: list[dict[str, Any]] = []

        # 1. Distinct relationship types in this workspace
        with self._connection() as conn:
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
                with self._connection() as conn:
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
            with self._connection() as conn:
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
                  (a IS aryx_graph_vertex WHERE a.entity_id = :src AND a.workspace_id = :ws)
                  -[r IS aryx_graph_edge]->{{1,{hops}}}  # nosec S608 — hops is a validated int
                  (b IS aryx_graph_vertex WHERE b.entity_id = :dst AND b.workspace_id = :ws2)
                )
                ONE ROW PER STEP (a, r, b)
                COLUMNS (
                  a.entity_id AS v1_id,
                  r.name      AS rel_name,
                  b.entity_id AS v2_id
                )
              )
        """
        # Scoping both path endpoints to this workspace is sufficient, not
        # just defense-in-depth: every edge/vertex is written with a single
        # workspace_id at ingest time (see e.g. neighbors_batch's WHERE
        # e.workspace_id = :ws), so no edge ever crosses a workspace
        # boundary -- a path that starts inside this workspace can never
        # traverse into another one.
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, {
                        "src": src, "dst": dst,
                        "ws": self._workspace_id, "ws2": self._workspace_id,
                    })
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
