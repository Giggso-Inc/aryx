"""FalkorStore's provenance/relationship write methods (mixin).

Split out of `graph/falkor_store.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). Same zero-patch-risk basis as `falkor_write_entities.py`.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class _FalkorRelationshipMixin:
    """add/remove relationship + provenance edge methods for FalkorStore."""

    def add_provenance(self, entity_id: int, system: str, dataset: str,
                       record_id: str) -> None:
        """Link an entity to the source record it was discovered in."""
        self._graph.query(
            "MERGE (s:Source {system: $sys, dataset: $ds, record_id: $rid}) "
            "WITH s MATCH (e:Entity {id: $id}) MERGE (e)-[:FROM]->(s)",
            {"sys": system, "ds": dataset, "rid": record_id, "id": entity_id},
        )

    def add_provenance_batch(
        self,
        rows: list[tuple[int, str, str, str]],
        batch_size: int = 500,
        on_batch: "Callable[[int], None] | None" = None,
    ) -> int:
        """Write multiple provenance links in batched UNWIND queries.

        Mirrors add_relationships_batch's UNWIND pattern (N/batch_size
        round-trips instead of N) and mirrors the Oracle graph store's
        existing add_provenance_batch — this was previously a
        FalkorDB-specific gap, not a deliberate cross-backend design
        choice. Combined with the Source.record_id index added in
        clear(), this is what actually closes the ~69-minute quadratic
        tail documented in docs/CPQ_INGESTION_PROJECTION_PERFORMANCE_PLAN.md
        — the index alone fixes the growth curve; batching removes the
        remaining per-row round-trip overhead on top of that.

        on_batch — optional callback invoked with the running total of rows
        written after each batch, for sub-progress reporting (see
        project.py's use of this in project_graph/project_incremental).
        """
        written = 0
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            params = [
                {"sys": sys_, "ds": ds, "rid": rid, "id": eid}
                for eid, sys_, ds, rid in chunk
            ]
            self._graph.query(
                "UNWIND $rows AS r "
                "MERGE (s:Source {system: r.sys, dataset: r.ds, record_id: r.rid}) "
                "WITH s, r MATCH (e:Entity {id: r.id}) MERGE (e)-[:FROM]->(s)",
                {"rows": params},
            )
            written += len(chunk)
            if on_batch is not None:
                on_batch(written)
        return written

    def neighbor_ids(self, ids: list[int]) -> list[int]:
        """Distinct ids of entities connected (either direction) to any of ``ids``.

        Used by project_incremental to capture a tombstone's neighbors
        *before* it's DETACH-DELETEd, so mark_isolated_entities() can be
        scoped to include them — deleting an entity's only edge can newly
        isolate the entity on the other end, and that entity is otherwise
        outside the incremental batch's own dirty set.
        """
        if not ids:
            return []
        rows = self._graph.query(
            "UNWIND $ids AS id MATCH (e:Entity {id: id})-[:REL]-(n:Entity) "
            "RETURN DISTINCT n.id",
            {"ids": ids},
        ).result_set
        return [r[0] for r in rows]

    def add_relationship(self, source_id: int, target_id: int, name: str) -> None:
        """Create a typed edge between two entities."""
        self._graph.query(
            "MATCH (a:Entity {id: $src}), (b:Entity {id: $tgt}) "
            "MERGE (a)-[:REL {name: $name}]->(b)",
            {"src": source_id, "tgt": target_id, "name": name},
        )

    def mark_isolated_entities(self, entity_ids: list[int] | None = None) -> None:
        """Stamp Entity nodes with a maintained ``isolated`` boolean.

        docs/graph_isolated_scan_gate — GraphReader.subgraph()'s Step 6 used
        to compute "has zero edges in either direction" live, per request,
        with `MATCH (e:Entity) WHERE NOT (e)-[:REL]-() AND NOT (e)<-[:REL]-()`
        — a structural check no index can accelerate, confirmed to take
        ~16.5s on a 344,961-entity workspace (~3.3x FalkorDB's query
        timeout), causing GET /graph to 500. That forced a tradeoff: skip
        the check (and the isolated nodes it surfaces) above a configurable
        size, or risk the timeout.

        Call this once here, at projection time (project_graph /
        project_incremental, right after relationships are written), so the
        expensive full-graph pass happens during ingest — which already
        takes minutes — not inside an interactive request. Reads become a
        cheap indexed `{isolated: true}` lookup (see ensure_indexes()'s
        index on this property), so Step 6 no longer needs a size gate at
        all: it's fast regardless of graph size.

        Args:
            entity_ids: When given, restricts both passes to just these
                entities instead of scanning the whole graph — used by
                project_incremental so a small dirty-set update doesn't pay
                a full-graph-scan cost proportional to total graph size
                (Raven review, PR #147 finding #2). project_graph passes
                None (a full rebuild needs every entity re-evaluated
                anyway, so a full scan there is already the right cost).

        Two full passes (true then false) rather than one combined
        expression — FalkorDB does not support assigning a pattern-existence
        check as a SET value directly.

        Best-effort: same structural scan Step 6 used to time out on for
        very large graphs, just moved here to write-time where an ingest
        job that already takes minutes can absorb it. Wrapped in try/except
        (mirroring ensure_indexes() just above) so a slow/timed-out pass on
        an exceptionally large graph degrades to a stale/missing `isolated`
        flag — Step 6 just returns fewer isolated nodes — instead of
        aborting the whole ingest job (Raven review, PR #147 finding #1).
        """
        if entity_ids is not None and not entity_ids:
            return
        scope = "WHERE e.id IN $ids AND " if entity_ids is not None else "WHERE "
        params = {"ids": entity_ids} if entity_ids is not None else {}
        try:
            self._graph.query(
                f"MATCH (e:Entity) {scope}NOT (e)-[:REL]-() AND NOT (e)<-[:REL]-() "
                "SET e.isolated = true",
                params,
            )
            self._graph.query(
                f"MATCH (e:Entity) {scope}((e)-[:REL]-() OR (e)<-[:REL]-()) "
                "SET e.isolated = false",
                params,
            )
        except Exception as exc:  # noqa: BLE001 — debug-visibility only, must not abort ingest
            logger.warning(
                "falkor: mark_isolated_entities failed, isolated-entity debug "
                "view may be stale/incomplete for %s: %s", self._graph.name, exc,
            )

    def add_relationships_batch(
        self,
        rels: list[tuple[int, int, str]],
        batch_size: int = 500,
        full_rebuild: bool = False,
    ) -> int:
        """Write multiple relationships in batched UNWIND queries.

        Uses UNWIND so N relationships cost ceil(N/batch_size) round-trips
        instead of N. Returns count of relationships written.

        full_rebuild — accepted for call-site parity with
        OracleGraphStore.add_relationships_batch, unused here (see
        add_entities_batch's docstring above).
        """
        written = 0
        for i in range(0, len(rels), batch_size):
            chunk = rels[i : i + batch_size]
            params = [{"src": s, "tgt": t, "name": n} for s, t, n in chunk]
            self._graph.query(
                "UNWIND $rels AS rel "
                "MATCH (a:Entity {id: rel.src}), (b:Entity {id: rel.tgt}) "
                "MERGE (a)-[:REL {name: rel.name}]->(b)",
                {"rels": params},
            )
            written += len(chunk)
        return written
