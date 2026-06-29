"""FalkorDB reader for the knowledge-graph projection (Increment 6).

Read counterpart to FalkorStore: looks up resolved entities, traverses their
one-hop relationships in both directions, and threads back to the source
records each entity was discovered in. Queries return scalar properties (never
raw Node objects) so callers get plain, serializable dicts.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB

from aryx.config import get_settings

logger = logging.getLogger(__name__)

# Module-level TTL cache for subgraph results.
# Each GET /graph fires N+1 FalkorDB queries (1 DISTINCT + 1 per type).
# Caching the result for 30 s collapses repeated canvas renders to 0 queries.
_subgraph_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SUBGRAPH_TTL: float = 30.0


class GraphReader:
    """Reads entities, relationships and provenance from the FalkorDB graph."""

    def __init__(self, url: str, graph: str = "aryx") -> None:
        """Connect from a redis:// URL and select a named graph.

        Args:
            url: FalkorDB connection URL, e.g. redis://falkordb:6379.
            graph: Graph key to read from.
        """
        parsed = urlparse(url)
        self._db = FalkorDB(host=parsed.hostname or "localhost",
                            port=parsed.port or 6379)
        self._graph = self._db.select_graph(graph)

    def get_entity(self, entity_id: int) -> dict[str, Any] | None:
        """Return a single entity's id/type/name, or None if absent."""
        rows = self._graph.query(
            "MATCH (e:Entity {id: $id}) RETURN e.id, e.type, e.name",
            {"id": entity_id},
        ).result_set
        return _entity(rows[0]) if rows else None

    def find_entities(self, ontology_type: str | None = None,
                      name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Find entities filtered by type and/or case-insensitive name match.

        Args:
            ontology_type: Exact ontology type to match, or None for any.
            name: Substring matched case-insensitively against the name, or None.
            limit: Maximum rows to return (coerced to int, capped at ARYX_GRAPH_QUERY_LIMIT).

        Returns:
            A list of {id, type, name} dicts.
        """
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if ontology_type:
            clauses.append("e.type = $type")
            params["type"] = ontology_type
        if name:
            clauses.append("toLower(e.name) CONTAINS toLower($name)")
            params["name"] = name
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        capped = max(1, min(int(limit), get_settings().graph_query_limit))
        rows = self._graph.query(
            f"MATCH (e:Entity) {where}RETURN e.id, e.type, e.name LIMIT {capped}",
            params,
        ).result_set
        return [_entity(r) for r in rows]

    def neighbors(self, entity_id: int) -> list[dict[str, Any]]:
        """Return one-hop related entities in both directions.

        Each result carries the edge name, its direction ('out' or 'in')
        relative to the queried entity, and the connected entity's fields.
        """
        rows = self._graph.query(
            "MATCH (e:Entity {id: $id})-[r:REL]->(n:Entity) "
            "RETURN n.id AS id, n.type AS type, n.name AS name, "
            "r.name AS rel, 'out' AS dir "
            "UNION "
            "MATCH (e:Entity {id: $id})<-[r:REL]-(n:Entity) "
            "RETURN n.id AS id, n.type AS type, n.name AS name, "
            "r.name AS rel, 'in' AS dir",
            {"id": entity_id},
        ).result_set
        return [{**_entity(r), "relationship": r[3], "direction": r[4]} for r in rows]

    def all_relationships(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return relationship edges in the graph, optionally capped."""
        cap = f" LIMIT {max(1, int(limit))}" if limit else ""
        rows = self._graph.query(
            f"MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN a.id, b.id, r.name{cap}"
        ).result_set
        return [{"source": r[0], "target": r[1], "name": r[2]} for r in rows]

    def subgraph(self, rel_limit: int = 500) -> dict[str, Any]:
        """Return a connected subgraph suitable for graph-canvas rendering.

        Samples proportionally from every edge type so all relationship kinds
        appear in the canvas.  After collecting relationship-connected entities,
        also fetches all remaining isolated entities (no edges) so every entity
        in the workspace is visible on the canvas regardless of connectivity.

        Results are cached for 30 s (per graph + rel_limit combination).
        """
        capped = max(1, min(int(rel_limit), get_settings().graph_query_limit))
        cache_key = f"{self._graph.name}:{capped}"
        now = time.monotonic()
        cached = _subgraph_cache.get(cache_key)
        if cached is not None:
            ts, result = cached
            if now - ts < _SUBGRAPH_TTL:
                return result

        # Discover the distinct relationship types present in this graph.
        type_rows = self._graph.query(
            "MATCH ()-[r:REL]->() RETURN DISTINCT r.name AS t"
        ).result_set
        rel_types = [r[0] for r in type_rows if r[0]]

        entity_map: dict[int, dict[str, Any]] = {}
        rels: list[dict[str, Any]] = []

        if rel_types:
            per_type = max(1, capped // len(rel_types))
            for rtype in rel_types:
                rows = self._graph.query(
                    "MATCH (a:Entity)-[r:REL]->(b:Entity) "
                    "WHERE r.name = $rname "
                    "RETURN a.id, a.type, a.name, b.id, b.type, b.name, r.name "
                    f"LIMIT {per_type}",
                    {"rname": rtype},
                ).result_set
                for row in rows:
                    aid, atype, aname, bid, btype, bname, rname = row
                    entity_map[aid] = {"id": aid, "type": atype, "name": aname}
                    entity_map[bid] = {"id": bid, "type": btype, "name": bname}
                    rels.append({"source": aid, "target": bid, "name": rname})

        # Always fetch all entities so isolated nodes (no relationships yet)
        # are visible on the canvas — entity count drives the ontology panel.
        remaining = capped - len(entity_map)
        if remaining > 0:
            all_rows = self._graph.query(
                f"MATCH (e:Entity) RETURN e.id, e.type, e.name LIMIT {capped}"
            ).result_set
            for row in all_rows:
                eid, etype, ename = row
                if eid not in entity_map:
                    entity_map[eid] = {"id": eid, "type": etype, "name": ename}

        result = {"entities": list(entity_map.values()), "relationships": rels}
        _subgraph_cache[cache_key] = (now, result)
        return result

    def provenance(self, entity_id: int) -> list[dict[str, Any]]:
        """Return the source records an entity was projected from."""
        rows = self._graph.query(
            "MATCH (e:Entity {id: $id})-[:FROM]->(s:Source) "
            "RETURN s.system, s.dataset, s.record_id",
            {"id": entity_id},
        ).result_set
        return [{"system": r[0], "dataset": r[1], "record_id": r[2]} for r in rows]

    def shortest_path(self, src: int, dst: int, max_hops: int = 6) -> list[dict[str, Any]]:
        """Return the shortest path between two entities (either direction), or []."""
        hops = max(1, min(int(max_hops), 10))
        # FalkorDB rejects undirected shortestPath, so try outbound then inbound
        # and keep whichever is shorter.
        candidates: list[tuple[list, list]] = []
        for arrow_a, arrow_b in (("-", "->"), ("<-", "-")):
            rows = self._graph.query(
                "MATCH (a:Entity {id: $a}), (b:Entity {id: $b}) "
                f"WITH shortestPath((a){arrow_a}[:REL*1..{hops}]{arrow_b}(b)) AS p "
                "WHERE p IS NOT NULL "
                "RETURN [n IN nodes(p) | [n.id, n.type, n.name]] AS ns, "
                "[r IN relationships(p) | r.name] AS rs",
                {"a": src, "b": dst},
            ).result_set
            if rows:
                candidates.append((rows[0][0], rows[0][1]))
        if not candidates:
            return []
        nodes, rels = min(candidates, key=lambda c: len(c[0]))
        rows = [(nodes, rels)]
        if not rows:
            return []
        nodes, rels = rows[0]
        steps: list[dict[str, Any]] = []
        for i, n in enumerate(nodes):
            steps.append({"id": n[0], "type": n[1], "name": n[2],
                          "relationship": rels[i - 1] if i > 0 else None})
        return steps


def _entity(row: list[Any]) -> dict[str, Any]:
    """Map an (id, type, name) result row to an entity dict."""
    return {"id": row[0], "type": row[1], "name": row[2]}
