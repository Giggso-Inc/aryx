"""FalkorDB reader for the knowledge-graph projection (Increment 6).

Read counterpart to FalkorStore: looks up resolved entities, traverses their
one-hop relationships in both directions, and threads back to the source
records each entity was discovered in. Queries return scalar properties (never
raw Node objects) so callers get plain, serializable dicts.
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
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

    def _query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        """Execute a Cypher query and return its result rows.

        `timeout_ms` (`ARYX_GRAPH_QUERY_TIMEOUT`, PR #121): caps how long
        FalkorDB will run any single query before aborting it — without this,
        a pathological query on a large workspace can hang the whole request
        indefinitely instead of failing fast.

        No per-query INFO-level logging here (2026-07-28): it flooded
        container logs on every graph read, drowning out other INFO-level
        diagnostics — see the earlier removal commit for the live-verified
        rationale.
        """
        timeout_ms = get_settings().graph_query_timeout or None
        return self._graph.query(cypher, params or {}, timeout=timeout_ms).result_set

    def get_entity(self, entity_id: int) -> dict[str, Any] | None:
        """Return a single entity's id/type/name/attributes, or None if absent."""
        rows = self._query(
            "MATCH (e:Entity {id: $id}) RETURN e.id, e.type, e.name, properties(e)",
            {"id": entity_id},
        )
        return _entity(rows[0]) if rows else None

    def distinct_types(self) -> list[str]:
        """Every distinct entity type in the graph — deterministic, no sampling.

        Callers that need "entities of a type matching X" must discover the
        type name here first, then find_entities(ontology_type=...). Sampling
        find_entities(limit=N) instead silently misses types on large graphs
        (a 46k-entity workspace can return a 1000-row page containing only
        2-3 dominant types).
        """
        rows = self._query("MATCH (e:Entity) RETURN DISTINCT e.type ORDER BY e.type")
        return [r[0] for r in rows if r[0]]

    def describe_schema(self, sample_per_type: int = 25) -> dict[str, Any]:
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
        types = self.distinct_types()
        rel_rows = self._query(
            "MATCH ()-[r:REL]->() RETURN DISTINCT r.name ORDER BY r.name")
        rel_names = [r[0] for r in rel_rows if r[0]]
        props_by_type: dict[str, list[str]] = {}
        for t in types:
            rows = self._query(
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

    def find_entities(self, ontology_type: str | None = None,
                      name: str | None = None, limit: int = 50,
                      offset: int = 0) -> list[dict[str, Any]]:
        """Find entities filtered by type and/or case-insensitive name match.

        Args:
            ontology_type: Exact ontology type to match, or None for any.
            name: Substring matched case-insensitively against the name, or None.
            limit: Maximum rows to return (coerced to int, capped at ARYX_GRAPH_QUERY_LIMIT).
            offset: Rows to skip before applying limit — paginate a
                single ontology_type past the ARYX_GRAPH_QUERY_LIMIT cap by
                calling repeatedly with offset += limit until a short page
                comes back (see CpqEngine.load_product_config's FK-fallback,
                confirmed live: SL3500e's >2000 bm_menu_item rows silently
                truncated at one capped call otherwise).
        Returns:
            A list of {id, type, name, attributes} dicts.
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
        skip = max(0, int(offset))
        rows = self._query(
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

    def neighbors(self, entity_id: int) -> list[dict[str, Any]]:
        """Return one-hop related entities in both directions.

        Each result carries the edge name, its direction ('out' or 'in')
        relative to the queried entity, and the connected entity's fields.
        """
        rows = self._query(
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

    def all_relationships(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return relationship edges in the graph, optionally capped."""
        cap = f" LIMIT {max(1, int(limit))}" if limit else ""
        rows = self._query(
            f"MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN a.id, b.id, r.name{cap}"
        )
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
           a batched query to find one real neighbor and add it.  Guarantees
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
        etype_rows = self._query(
            "MATCH (e:Entity) RETURN DISTINCT e.type ORDER BY e.type"
        )
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
            rtype_rows = self._query(
                "MATCH ()-[r:REL]->() RETURN DISTINCT r.name ORDER BY r.name"
            )
            rel_types = [r[0] for r in rtype_rows if r[0]]

            # N rels per relationship type: enough to cover per_type entities
            # on each side.  Use at least per_type*2 so high-degree nodes get
            # good coverage even when relationship types are many.
            n_rel_types = max(1, len(rel_types))
            rels_per_rtype = max(per_type * 2, capped // n_rel_types)

            raw_rels: list[tuple] = []   # (src_id, tgt_id, rname)
            entity_info: dict[int, dict[str, Any]] = {}
            for rname in rel_types:
                rows = self._query(
                    "MATCH (a:Entity)-[r:REL {name: $rname}]->(b:Entity) "
                    "RETURN a.id, a.type, a.name, properties(a), b.id, b.type, b.name, properties(b) "
                    f"LIMIT {rels_per_rtype}",
                    {"rname": rname},
                )
                for row in rows:
                    aid, atype, aname, aattrs, bid, btype, bname, battrs = row
                    entity_info[aid] = _entity([aid, atype, aname, aattrs])
                    entity_info[bid] = _entity([bid, btype, bname, battrs])
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
            rel_count: Counter[int] = Counter()
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
                    rows = self._query(
                        "MATCH (e:Entity {type: $type}) "
                        "RETURN e.id, e.type, e.name, properties(e) "
                        f"LIMIT {per_type}",
                        {"type": etype},
                    )
                    for row in rows:
                        entity_map[row[0]] = _entity(row)
                        valid_ids.add(row[0])

        # Step 5 — post-linking pass (batched): guarantee every entity has a
        # visible edge.  Two UNWIND queries replace N×LIMIT 1 round-trips.
        # First pass: outbound neighbors for all still-isolated entities.
        # Second pass: inbound neighbors for any still-isolated after the first.
        if entity_map:
            connected_ids: set[int] = set()
            for r in rels:
                connected_ids.add(r["source"])
                connected_ids.add(r["target"])
            isolated_eids = [eid for eid in entity_map if eid not in connected_ids]
            if isolated_eids:
                # Group by eid and take one neighbor per entity (collect(...)[0])
                # *before* returning, so the row count is naturally bounded by
                # len(ids) regardless of any single entity's degree. A flat
                # LIMIT here would let one high-degree hub in the batch consume
                # the entire cap and starve every other id of a result.
                found: dict[int, tuple] = {}
                out_rows = self._query(
                    "UNWIND $ids AS eid "
                    "MATCH (a:Entity {id: eid})-[r:REL]->(b:Entity) "
                    "WITH eid, collect({bid: b.id, btype: b.type, bname: b.name, "
                    "battrs: properties(b), rname: r.name})[0] AS pick "
                    "RETURN eid, pick.bid, pick.btype, pick.bname, pick.battrs, pick.rname",
                    {"ids": isolated_eids},
                )
                for row in out_rows:
                    eid_ = row[0]
                    if eid_ not in found:
                        found[eid_] = (row[1], row[2], row[3], row[4], row[5], "out")
                still_iso = [e for e in isolated_eids if e not in found]
                if still_iso:
                    in_rows = self._query(
                        "UNWIND $ids AS eid "
                        "MATCH (b:Entity)-[r:REL]->(a:Entity {id: eid}) "
                        "WITH eid, collect({bid: b.id, btype: b.type, bname: b.name, "
                        "battrs: properties(b), rname: r.name})[0] AS pick "
                        "RETURN eid, pick.bid, pick.btype, pick.bname, pick.battrs, pick.rname",
                        {"ids": still_iso},
                    )
                    for row in in_rows:
                        eid_ = row[0]
                        if eid_ not in found:
                            found[eid_] = (row[1], row[2], row[3], row[4], row[5], "in")
                for eid, (bid, btype, bname, battrs, rname, direction) in found.items():
                    entity_map[bid] = _entity([bid, btype, bname, battrs])
                    valid_ids.add(bid)
                    if direction == "out":
                        rels.append({"source": eid, "target": bid, "name": rname})
                    else:
                        rels.append({"source": bid, "target": eid, "name": rname})
                    connected_ids.add(eid)
                    connected_ids.add(bid)

        # Step 6 — add truly isolated entities (zero edges in FalkorDB, not
        # just in the subgraph view) for debugging visibility.
        #
        # docs/graph_isolated_scan_gate — this used to compute "has zero
        # edges in either direction" live, per request
        # (`MATCH (e:Entity) WHERE NOT (e)-[:REL]-() AND NOT (e)<-[:REL]-()`)
        # — a structural check no index can accelerate. Confirmed live: that
        # query alone took ~16.5s on a 344,961-entity workspace, ~3.3x over
        # FalkorDB's default 5000ms timeout, causing GET /graph to 500 even
        # after the REL.name index fix — and it kept recurring on any
        # workspace that grew past the size a 5-30s query budget could cover,
        # regardless of where a size-gate threshold was set.
        #
        # Fixed at the source instead of gated: FalkorStore.mark_isolated_
        # entities() now stamps every Entity's `isolated` boolean once, at
        # projection time (project_graph / project_incremental — an ingest
        # job that already takes minutes easily absorbs one more full-graph
        # pass), with an index on that property (ensure_indexes()). This
        # query is now a cheap indexed lookup regardless of graph size, so
        # Step 6 no longer needs to skip itself, or the isolated nodes it
        # surfaces, on any workspace.
        remaining = capped - len(entity_map)
        if remaining > 0:
            iso_rows = self._query(
                "MATCH (e:Entity {isolated: true}) "
                f"RETURN e.id, e.type, e.name, properties(e) LIMIT {remaining}"
            )
            for row in iso_rows:
                if row[0] not in entity_map:
                    entity_map[row[0]] = _entity(row)

        result = {"entities": list(entity_map.values()), "relationships": rels}
        _subgraph_cache[cache_key] = (now, result)
        return result

    def provenance(self, entity_id: int) -> list[dict[str, Any]]:
        """Return the source records an entity was projected from."""
        rows = self._query(
            "MATCH (e:Entity {id: $id})-[:FROM]->(s:Source) "
            "RETURN s.system, s.dataset, s.record_id",
            {"id": entity_id},
        )
        return [{"system": r[0], "dataset": r[1], "record_id": r[2]} for r in rows]

    def shortest_path(self, src: int, dst: int, max_hops: int = 6) -> list[dict[str, Any]]:
        """Return the shortest path between two entities (either direction), or []."""
        hops = max(1, min(int(max_hops), 10))
        # FalkorDB rejects undirected shortestPath, so try outbound then inbound
        # and keep whichever is shorter.
        candidates: list[tuple[list, list]] = []
        for arrow_a, arrow_b in (("-", "->"), ("<-", "-")):
            rows = self._query(
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
        rows = [(nodes, rels)]
        if not rows:
            return []
        nodes, rels = rows[0]
        steps: list[dict[str, Any]] = []
        for i, n in enumerate(nodes):
            steps.append({**_entity(n), "relationship": rels[i - 1] if i > 0 else None})
        return steps


# Node properties written by the projection itself, not entity attributes.
_INTERNAL_PROPS = frozenset({"id", "type", "name", "iri"})


def _parse_attrs(raw: Any) -> dict[str, Any]:
    """Extract entity attributes from a node's property map.

    Current graphs store attributes as individual native node properties, so
    ``raw`` is the properties() map minus the internal projection fields.
    Graphs projected before the native-property lift carry a single
    stringified JSON blob under ``attrs`` — decode and merge it so reads work
    against both generations without a reprojection.
    """
    if not raw:
        return {}
    if isinstance(raw, str):  # legacy: bare attrs blob
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if isinstance(raw, dict):
        attrs: dict[str, Any] = {}
        for k, v in raw.items():
            if k in _INTERNAL_PROPS or k == "attrs":
                continue
            # Source attrs whose names collide with projection fields are
            # written as src_id / src_name / ... — map them back so callers
            # see the original attribute names.
            if k.startswith("src_") and k[4:] in _INTERNAL_PROPS:
                attrs.setdefault(k[4:], v)
            else:
                attrs[k] = v
        legacy = raw.get("attrs")
        if isinstance(legacy, str) and legacy:
            try:
                attrs = {**json.loads(legacy), **attrs}
            except (TypeError, ValueError):
                pass
        return attrs
    return {}


def _entity(row: list[Any]) -> dict[str, Any]:
    """Map an (id, type, name[, attrs]) result row to an entity dict."""
    entity: dict[str, Any] = {"id": row[0], "type": row[1], "name": row[2]}
    if len(row) > 3:
        entity["attributes"] = _parse_attrs(row[3])
    return entity
