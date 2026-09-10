"""Subgraph-builder algorithm for GraphReader.subgraph() (graph-canvas view).

Split out of `graph/reader.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). `GraphReader.subgraph()` reads `get_settings().graph_query_limit`
itself (kept in reader.py so existing `aryx.graph.reader.get_settings`
whitebox patches keep intercepting it) and passes the already-capped limit
plus its own `_query` bound method in here — this module never calls
`get_settings()`.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any, Callable

from aryx.graph.reader_entity import _entity

# Module-level TTL cache for subgraph results.
# Each GET /graph fires N+1 FalkorDB queries (1 DISTINCT + 1 per type).
# Caching the result for 30 s collapses repeated canvas renders to 0 queries.
_subgraph_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SUBGRAPH_TTL: float = 30.0

_Query = Callable[..., list[list[Any]]]


def _build_subgraph(query: _Query, graph_name: str, capped: int) -> dict[str, Any]:
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
    cache_key = f"{graph_name}:{capped}"
    now = time.monotonic()
    cached = _subgraph_cache.get(cache_key)
    if cached is not None:
        ts, result = cached
        if now - ts < _SUBGRAPH_TTL:
            return result

    # Step 1 — entity types present in this graph.
    etype_rows = query(
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
        rtype_rows = query(
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
            rows = query(
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
                rows = query(
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
            out_rows = query(
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
                in_rows = query(
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
        iso_rows = query(
            "MATCH (e:Entity {isolated: true}) "
            f"RETURN e.id, e.type, e.name, properties(e) LIMIT {remaining}"
        )
        for row in iso_rows:
            if row[0] not in entity_map:
                entity_map[row[0]] = _entity(row)

    result = {"entities": list(entity_map.values()), "relationships": rels}
    _subgraph_cache[cache_key] = (now, result)
    return result
