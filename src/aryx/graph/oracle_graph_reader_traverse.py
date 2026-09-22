"""Subgraph sampling + SQL/PGQ shortest-path traversal, mixed into
OracleGraphReader.

Split out of `graph/oracle_graph_reader.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). `shortest_path` is exercised directly by
`tests/test_oracle_graph_reader_shortest_path_scope.py` via the real
`OracleGraphReader` class (no patches) — confirmed via grep.

2026-09-10: subgraph()'s relationship-type discovery scan and per-type
fan-out (below) mirror the fix ported into GraphReader.subgraph()'s
FalkorDB counterpart (graph/reader_subgraph.py, dev-rv-msi #316,
docs/GRAPH_SUBGRAPH_LARGE_WORKSPACE_PERFORMANCE_2026_09_02.md) — same
performance shape (a full-scan-required type-discovery query, then N
sequential per-type queries, each independently slow at scale), same
class of fix (cache the type list with a longer TTL since it changes far
less often than the sampled subgraph; fan the per-type queries out over
a small worker pool, each on its own pooled connection). Unlike
FalkorDB, this table had NO index at all on (workspace_id, name) before
this pass (added in migrations_oracle/graph_schema.sql) — the missing
index is the more fundamental fix; the cache + fan-out on top are the
same defense-in-depth this codebase already applies to the FalkorDB
path.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from aryx.config import get_settings
from aryx.graph.oracle_graph_reader_helpers import _entity

logger = logging.getLogger(__name__)

# Module-level TTL cache for subgraph results — mirrors reader_subgraph.
# py's _subgraph_cache/_SUBGRAPH_TTL for the FalkorDB path. Without this,
# every /graph request re-runs the full type-discovery + per-type-fan-out
# query set even for back-to-back repeated calls (page navigation,
# multiple viewers of the same workspace).
_subgraph_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SUBGRAPH_TTL: float = 30.0

# Longer-lived cache for the relationship-type discovery scan (`SELECT
# DISTINCT name FROM aryx_graph_edge WHERE workspace_id = :1`) — a
# full-table scan of every edge in the workspace regardless of indexing on
# `name` alone (the index added alongside this fix covers (workspace_id,
# name), which helps, but the set of relationship TYPES present still
# changes far less often than the sampled subgraph itself, so it's still
# worth avoiding on every _subgraph_cache miss). Mirrors reader_subgraph.
# py's _types_cache/_TYPES_TTL for the FalkorDB path.
_types_cache: dict[str, tuple[float, list[str]]] = {}
_TYPES_TTL: float = 300.0

# Bound on concurrent per-relationship-type sampling queries. Each worker
# borrows its own connection from the shared Oracle connection pool
# (self._connection()) — safe precisely because a pool, unlike a single
# shared connection, is designed to hand out independent connections to
# concurrent callers.
_MAX_RTYPE_WORKERS: int = 8


class _OracleGraphTraverseMixin:
    """subgraph / shortest_path, mixed into OracleGraphReader."""

    def subgraph(self, rel_limit: int = 500) -> dict[str, Any]:
        """Return a connected subgraph for graph-canvas rendering.

        Mirrors FalkorReader.subgraph(): samples proportionally from every
        relationship type then fills remaining slots with isolated entities.
        """
        capped = max(1, min(int(rel_limit), get_settings().graph_query_limit))
        cache_key = f"{self.graph_name}:{capped}"
        now = time.monotonic()
        cached_result = _subgraph_cache.get(cache_key)
        if cached_result is not None:
            ts, result = cached_result
            if now - ts < _SUBGRAPH_TTL:
                return result

        entity_map: dict[int, dict[str, Any]] = {}
        rels: list[dict[str, Any]] = []

        # 1. Distinct relationship types in this workspace, from the
        # longer-TTL _types_cache when fresh.
        types_cache_key = self.graph_name
        cached = _types_cache.get(types_cache_key)
        if cached is not None and now - cached[0] < _TYPES_TTL:
            rel_types = cached[1]
        else:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT name FROM aryx_graph_edge WHERE workspace_id = :1",
                        (self._workspace_id,),
                    )
                    rel_types = [r[0] for r in cur.fetchall() if r[0]]
            _types_cache[types_cache_key] = (now, rel_types)

        # 2. Sample edges proportionally per type — fanned out over a small
        # worker pool instead of run sequentially, since each per-type query
        # is independently slow on a large workspace (same reasoning as the
        # FalkorDB path this mirrors).
        if rel_types:
            per_type = max(1, capped // len(rel_types))
            rtype_sql = f"""
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
                """  # nosec S608 — per_type is a validated int

            def _fetch_rtype(rtype: str) -> tuple[str, list[tuple]]:
                with self._connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(rtype_sql, {"ws": self._workspace_id, "rel": rtype})
                        return rtype, cur.fetchall()

            max_workers = min(_MAX_RTYPE_WORKERS, len(rel_types))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(_fetch_rtype, rtype) for rtype in rel_types]
                for future in as_completed(futures):
                    _rtype, rows = future.result()
                    for row in rows:
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

        result = {"entities": list(entity_map.values()), "relationships": rels}
        _subgraph_cache[cache_key] = (now, result)
        return result

    def shortest_path(self, src: int, dst: int, max_hops: int = 6) -> list[dict[str, Any]]:
        """Return shortest path using Oracle 26ai SQL/PGQ GRAPH_TABLE ONE ROW PER STEP.

        ONE ROW PER STEP (v1, e, v2) returns one row per edge in the path, each
        carrying (left_vertex, edge, right_vertex) properties. We collect all steps
        then resolve entity details for each unique vertex.
        """
        hops = max(1, min(int(max_hops), 10))
        # ONE ROW PER STEP is the correct Oracle 26ai syntax for path traversal.
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
