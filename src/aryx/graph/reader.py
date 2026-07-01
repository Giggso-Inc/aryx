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

    def subgraph(self, rel_limit: int = 2000) -> dict[str, Any]:
        """Return a connected subgraph suitable for graph-canvas rendering.

        Algorithm (all steps run per cache miss):
        1. Discover entity types and relationship types.
        2. Sample rels_per_rtype rels per relationship type so every rel class
           is represented and source/target pairs are loaded together.
        3. Greedy per-type cap: process rels from highest combined endpoint
           degree to lowest; include both endpoints only if each type still has
           room under the per_type cap.  Guarantees included entities are hubs
           that connect across types.
        4. Seed any entity type with zero rels so all types appear on canvas.
        5. Post-linking pass: for any entity still without a visible edge, run
           a LIMIT 1 query to find one real neighbor and add it.  Guarantees
           zero isolated nodes in the rendered canvas.
        6. Add truly isolated FalkorDB entities (no edges at all) for debugging.

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

        # Step 1 — entity types present in this graph.
        etype_rows = self._graph.query(
            "MATCH (e:Entity) RETURN DISTINCT e.type ORDER BY e.type"
        ).result_set
        entity_types = [r[0] for r in etype_rows if r[0]]

        entity_map: dict[int, dict[str, Any]] = {}
        rels: list[dict[str, Any]] = []
        seen_rels: set[tuple] = set()
        valid_ids: set[int] = set()

        if entity_types:
            per_type = max(5, min(50, capped // max(1, len(entity_types))))

            # Step 2 — discover relationship types present in this graph.
            # Sampling by relationship type (not entity type) ensures connected
            # source→target pairs are loaded together, so their endpoints are
            # co-present and survive the per-type cap as a matched pair.
            rtype_rows = self._graph.query(
                "MATCH ()-[r:REL]->() RETURN DISTINCT r.name ORDER BY r.name"
            ).result_set
            rel_types = [r[0] for r in rtype_rows if r[0]]

            # N rels per relationship type: enough to cover per_type entities
            # on each side.  Use at least per_type*2 so high-degree nodes get
            # good coverage even when relationship types are many.
            n_rel_types = max(1, len(rel_types))
            rels_per_rtype = max(per_type * 2, capped // n_rel_types)

            raw_rels: list[tuple] = []   # (src_id, tgt_id, rname)
            entity_info: dict[int, dict[str, Any]] = {}
            for rname in rel_types:
                rows = self._graph.query(
                    "MATCH (a:Entity)-[r:REL {name: $rname}]->(b:Entity) "
                    "RETURN a.id, a.type, a.name, b.id, b.type, b.name "
                    f"LIMIT {rels_per_rtype}",
                    {"rname": rname},
                ).result_set
                for row in rows:
                    aid, atype, aname, bid, btype, bname = row
                    entity_info[aid] = {"id": aid, "type": atype, "name": aname}
                    entity_info[bid] = {"id": bid, "type": btype, "name": bname}
                    key = (aid, bid, rname)
                    if key not in seen_rels:
                        seen_rels.add(key)
                        raw_rels.append((aid, bid, rname))

            # Step 3 — greedy per-type cap that GUARANTEES every included
            # entity has at least one visible rel.  Process rels from most
            # connected pair to least; add both endpoints when either (a) the
            # endpoint is already in the valid set, or (b) its type hasn't
            # reached the per_type cap yet.  Skip a rel only when BOTH
            # endpoints would exceed their caps — they'll appear in a later
            # rel or be filled from seeds in step 4.
            from collections import Counter as _Counter
            rel_count: _Counter[int] = _Counter()
            for sid, tid, _ in raw_rels:
                rel_count[sid] += 1
                rel_count[tid] += 1

            # Sort rels: highest combined endpoint degree first so the most
            # hub-like cross-type connections are processed before the caps fill.
            sorted_raw = sorted(
                raw_rels,
                key=lambda r: -(rel_count.get(r[0], 0) + rel_count.get(r[1], 0)),
            )

            type_count: dict[str, int] = {}

            for sid, tid, rname in sorted_raw:
                stype = entity_info[sid]["type"]
                ttype = entity_info[tid]["type"]
                s_in = sid in valid_ids
                t_in = tid in valid_ids
                s_cap_ok = s_in or type_count.get(stype, 0) < per_type
                t_cap_ok = t_in or type_count.get(ttype, 0) < per_type
                if not (s_cap_ok and t_cap_ok):
                    continue   # both would exceed cap — skip
                if not s_in:
                    valid_ids.add(sid)
                    entity_map[sid] = entity_info[sid]
                    type_count[stype] = type_count.get(stype, 0) + 1
                if not t_in:
                    valid_ids.add(tid)
                    entity_map[tid] = entity_info[tid]
                    type_count[ttype] = type_count.get(ttype, 0) + 1
                rels.append({"source": sid, "target": tid, "name": rname})

            # Step 4 — add sample entities for types with zero rels so all
            # entity types appear on the canvas.
            for etype in entity_types:
                if type_count.get(etype, 0) == 0:
                    rows = self._graph.query(
                        "MATCH (e:Entity {type: $type}) "
                        "RETURN e.id, e.type, e.name "
                        f"LIMIT {per_type}",
                        {"type": etype},
                    ).result_set
                    for row in rows:
                        eid, et, en = row
                        entity_map[eid] = {"id": eid, "type": et, "name": en}
                        valid_ids.add(eid)

        # Step 5 — post-linking pass: guarantee every entity has a visible edge.
        # For entities whose specific neighbors are not in valid_ids, add ONE
        # real neighbor from FalkorDB directly (allowing the per-type cap to be
        # exceeded by a small margin rather than leaving nodes isolated).
        # Each query is LIMIT 1 — cheap even at 50-100 isolated entities.
        if entity_map:
            connected_ids: set[int] = set()
            for r in rels:
                connected_ids.add(r["source"])
                connected_ids.add(r["target"])
            for eid in list(entity_map.keys()):
                if eid in connected_ids:
                    continue
                # Try outbound first
                rows = self._graph.query(
                    "MATCH (a:Entity {id: $id})-[r:REL]->(b:Entity) "
                    "RETURN b.id, b.type, b.name, r.name LIMIT 1",
                    {"id": eid},
                ).result_set
                if rows:
                    bid, btype, bname, rname = rows[0]
                    entity_map[bid] = {"id": bid, "type": btype, "name": bname}
                    valid_ids.add(bid)
                    rels.append({"source": eid, "target": bid, "name": rname})
                    connected_ids.add(eid)
                    connected_ids.add(bid)
                    continue
                # Try inbound
                rows = self._graph.query(
                    "MATCH (b:Entity)-[r:REL]->(a:Entity {id: $id}) "
                    "RETURN b.id, b.type, b.name, r.name LIMIT 1",
                    {"id": eid},
                ).result_set
                if rows:
                    bid, btype, bname, rname = rows[0]
                    entity_map[bid] = {"id": bid, "type": btype, "name": bname}
                    valid_ids.add(bid)
                    rels.append({"source": bid, "target": eid, "name": rname})
                    connected_ids.add(eid)
                    connected_ids.add(bid)

        # Step 6 — add truly isolated entities (zero edges in FalkorDB, not just
        # in the subgraph view) for debugging visibility.
        remaining = capped - len(entity_map)
        if remaining > 0:
            iso_rows = self._graph.query(
                "MATCH (e:Entity) WHERE NOT (e)-[:REL]-() AND NOT (e)<-[:REL]-() "
                f"RETURN e.id, e.type, e.name LIMIT {remaining}"
            ).result_set
            for row in iso_rows:
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
