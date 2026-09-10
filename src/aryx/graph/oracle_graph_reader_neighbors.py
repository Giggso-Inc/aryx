"""Neighbor/relationship/provenance reads, mixed into OracleGraphReader.

Split out of `graph/oracle_graph_reader.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

from typing import Any

from aryx.graph.oracle_graph_reader_helpers import _entity


class _OracleGraphNeighborsMixin:
    """neighbors / neighbors_batch / all_relationships / provenance, mixed into OracleGraphReader."""

    def neighbors(self, entity_id: int) -> list[dict[str, Any]]:
        """Return one-hop related entities in both directions with relationship name and direction."""
        with self._connection() as conn:
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

    def neighbors_batch(self, entity_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        """Batch one-hop neighbor lookup for multiple entities in one round-trip.

        neighbors() called once per entity is a real N+1 cost against a remote
        Oracle ADB — confirmed live at ~750ms/call, so a 235-entity CPQ product
        config took ~3 minutes just for this step (see CpqEngine.load_product_config
        Step 3). One batched query replaces N round-trips with 1.

        Each named bind (:ws, :ids) is used exactly once per SELECT branch with
        its own numbered variant -- oracledb's thin client binds positional-style
        IN-list expansions by textual occurrence, so the workspace_id and id-list
        placeholders are duplicated (suffixed _2) for the second branch rather
        than reused, matching the pattern already required by ask_thread_touch_thread.sql.
        """
        if not entity_ids:
            return {}
        ids = list(entity_ids)
        out_binds = ",".join(f":o{i}" for i in range(len(ids)))
        in_binds = ",".join(f":i{i}" for i in range(len(ids)))
        params: dict[str, Any] = {"ws": self._workspace_id, "ws2": self._workspace_id}
        params.update({f"o{i}": v for i, v in enumerate(ids)})
        params.update({f"i{i}": v for i, v in enumerate(ids)})
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT e.src_id AS src, v.entity_id, v.type, v.name, v.attributes,
                           e.name AS rel, 'out' AS dir
                      FROM aryx_graph_edge e
                      JOIN aryx_graph_vertex v
                        ON v.workspace_id = e.workspace_id AND v.entity_id = e.tgt_id
                     WHERE e.workspace_id = :ws AND e.src_id IN ({out_binds})
                    UNION ALL
                    SELECT e.tgt_id AS src, v.entity_id, v.type, v.name, v.attributes,
                           e.name AS rel, 'in' AS dir
                      FROM aryx_graph_edge e
                      JOIN aryx_graph_vertex v
                        ON v.workspace_id = e.workspace_id AND v.entity_id = e.src_id
                     WHERE e.workspace_id = :ws2 AND e.tgt_id IN ({in_binds})
                    """,  # nosec S608 — out_binds/in_binds are generated bind-name placeholders, not interpolated values
                    params,
                )
                rows = cur.fetchall()
        result: dict[int, list[dict[str, Any]]] = {eid: [] for eid in ids}
        for src, eid, typ, name, attrs, rel, direction in rows:
            result.setdefault(int(src), []).append(
                {**_entity((eid, typ, name, attrs)), "relationship": rel, "direction": direction}
            )
        return result

    def all_relationships(self) -> list[dict[str, Any]]:
        """Return every relationship edge in this workspace as {source, target, name}."""
        with self._connection() as conn:
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
        with self._connection() as conn:
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
