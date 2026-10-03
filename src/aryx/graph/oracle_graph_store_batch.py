"""Batch write methods for the Oracle Property Graph writer — one Oracle
round-trip per phase, mixed into OracleGraphStore.

Split out of `graph/oracle_graph_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from aryx.config import get_settings
from aryx.graph.oracle_graph_store_helpers import _display_name, _iter_chunks, _safe_attrs_json
from aryx.queries import load
from aryx.raven_log import raven_log, submit_ctx

logger = logging.getLogger(__name__)


class _OracleGraphBatchMixin:
    """Batch methods — one Oracle round-trip per phase, mixed into OracleGraphStore."""

    def _write_chunks(
        self,
        chunks: list[list[dict]],
        query_name: str,
        on_batch: "Callable[[int], None] | None",
    ) -> int:
        """Execute one `executemany` per chunk, sequentially or concurrently.

        Chunks must be independent (disjoint entity ids / edges) — used by
        add_entities_batch and add_relationships_batch, not by
        add_provenance_batch (which has an internal read-after-write
        dependency between its three steps and stays sequential within one
        connection). docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_
        2026-09-23.md Phase 4 Part B.

        Concurrent chunks each acquire their own connection from the pool
        (never share one across threads) -- the same pattern already
        proven safe for ProjectionStore/schema-FK batches/embedding
        prefetch in Phases 1-3. on_batch fires with the running total after
        each chunk completes, in COMPLETION order, not submission order --
        callers must treat it as a progress total, not a per-chunk sequence.
        """
        sql = load(query_name)
        workers = max(1, get_settings().oracle_graph_batch_workers)
        written = 0
        _t0 = time.monotonic()
        _sequential = len(chunks) <= 1 or workers <= 1
        raven_log("DEBUG", "P4", "ingest.project.write_chunks graph chunk write mode",
                  context={"stage": "project", "query": query_name, "chunks": len(chunks), "workers": workers,
                           "selected_option": "sequential" if _sequential else "concurrent",
                           "available_options": ["sequential", "concurrent"],
                           "reason_code": "ONE_CHUNK_OR_ONE_WORKER" if _sequential else "MULTI_CHUNK_MULTI_WORKER",
                           "backend": "oci_graph"})
        if _sequential:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    for chunk in chunks:
                        _tc = time.monotonic()
                        cur.executemany(sql, chunk)
                        raven_log("DEBUG", "P4", "ingest.project.chunk_written graph chunk written",
                                  context={"stage": "project", "query": query_name, "rows": len(chunk),
                                           "duration_ms": int((time.monotonic() - _tc) * 1000)})
                        written += len(chunk)
                        logger.info("graph %s chunk rows=%d done", query_name, len(chunk))
                        if on_batch is not None:
                            on_batch(written)
            return written

        def _write_one(chunk: list[dict]) -> int:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.executemany(sql, chunk)
            return len(chunk)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [submit_ctx(pool, _write_one, chunk) for chunk in chunks]
            for future in as_completed(futures):
                n = future.result()
                written += n
                raven_log("DEBUG", "P4", "ingest.project.chunk_written graph chunk written",
                          context={"stage": "project", "query": query_name, "rows": n, "written_total": written,
                                   "elapsed_ms": int((time.monotonic() - _t0) * 1000)})
                logger.info("graph %s chunk rows=%d done", query_name, n)
                if on_batch is not None:
                    on_batch(written)
        return written

    def add_entities_batch(
        self,
        rows: list[tuple[int, str, dict, list | None, str | None]],
        on_batch: "Callable[[int], None] | None" = None,
        full_rebuild: bool = False,
    ) -> int:
        """Batch-upsert entity vertices in Oracle round-trips, one per chunk.

        Each row: (entity_id, ontology_type, attributes, labels, iri).
        ``labels`` is accepted for API parity with add_entity but not stored
        (Oracle backing table has no labels column).

        on_batch — optional callback invoked with the running total of rows
        written after each executemany chunk, for sub-progress reporting
        (mirrors FalkorGraphStore.add_entities_batch).

        full_rebuild — True only for project_graph()'s full-rebuild path
        (clear() then rewrite everything), never for project_incremental().
        Switches merge_graph_vertex (MERGE, upsert-safe for a possibly
        non-empty graph) to insert_graph_vertex (plain INSERT, valid only
        because clear() guarantees no existing rows can conflict). Not a
        micro-optimization: live-measured (docs/ingestion/SPARK_PARALLEL_
        MIGRATION_ANALYSIS_2026-09-23.md Phase 4 Part B follow-up), a
        500-row MERGE executemany() batch hung 180+ seconds against a real
        Oracle ADB with zero conflicting rows and zero lock contention;
        the equivalent plain INSERT batch completed in well under a
        second. Accepted (not used) by FalkorStore too, for call-site
        parity -- FalkorDB's Cypher MERGE has no equivalent pathology.
        """
        if not rows:
            return 0
        logger.info("graph vertices batch start count=%d", len(rows))
        # Build and deduplicate by (ws, eid) — same entity from multiple source rows
        # keeps last occurrence. Prevents ORA-00001 within a single executemany batch.
        seen: dict[tuple, dict] = {}
        for eid, typ, attrs, _labels, iri in rows:
            seen[(self._workspace_id, eid)] = {
                "ws": self._workspace_id,
                "eid": eid,
                "typ": typ,
                "name": _display_name(attrs) or f"#{eid}",
                "iri": iri or "",
                "attrs": _safe_attrs_json(attrs),
            }
        batch = list(seen.values())
        chunks = list(_iter_chunks(batch, payload_key="attrs"))
        query_name = "insert_graph_vertex" if full_rebuild else "merge_graph_vertex"
        written = self._write_chunks(chunks, query_name, on_batch)
        logger.info("graph vertices batch done count=%d", len(rows))
        return written

    def add_provenance_batch(
        self,
        rows: list[tuple[int, str, str, str]],
        on_batch: "Callable[[int], None] | None" = None,
    ) -> int:
        """Batch-upsert provenance edges in three Oracle round-trips.

        Each row: (entity_id, system, dataset, record_id).

        Steps within one connection/transaction:
          1. executemany merge_graph_source   — upsert all source records
          2. SELECT source_id back for the workspace
          3. executemany merge_graph_provenance — link entity → source

        on_batch — optional callback invoked with the running total of
        provenance links written after each executemany chunk in step 3
        (mirrors FalkorGraphStore.add_provenance_batch).
        """
        if not rows:
            return 0
        logger.info("graph provenance batch start count=%d", len(rows))
        source_rows = [
            {"ws": self._workspace_id, "sys": system, "ds": dataset, "rid": record_id}
            for _eid, system, dataset, record_id in rows
        ]
        missing = 0
        written = 0
        prov_rows: list[dict] = []
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for i, chunk in enumerate(_iter_chunks(source_rows, payload_key="rid")):
                    cur.executemany(load("merge_graph_source"), chunk)
                    logger.info("graph sources chunk=%d rows=%d done", i + 1, len(chunk))
                logger.info("graph sources merged count=%d — fetching source_ids", len(source_rows))
                cur.execute(
                    load("select_graph_sources_by_workspace"),
                    (self._workspace_id,),
                )
                source_map: dict[tuple[str, str, str], int] = {
                    (r[1], r[2], r[3]): int(r[0]) for r in cur.fetchall()
                }
                logger.info("graph source_ids resolved %d — building provenance links", len(source_map))
                for eid, system, dataset, record_id in rows:
                    sid = source_map.get((system, dataset, record_id))
                    if sid is None:
                        missing += 1
                        continue
                    prov_rows.append({"ws": self._workspace_id, "eid": eid, "sid": sid})
                if missing:
                    logger.warning("graph provenance batch: %d source_ids not found — skipped", missing)
                logger.info("graph provenance links ready=%d — inserting", len(prov_rows))
                if prov_rows:
                    for i, chunk in enumerate(_iter_chunks(prov_rows, payload_key="sid")):
                        cur.executemany(load("merge_graph_provenance"), chunk)
                        written += len(chunk)
                        logger.info("graph provenance chunk=%d rows=%d done", i + 1, len(chunk))
                        if on_batch is not None:
                            on_batch(written)
        logger.info("graph provenance batch done prov=%d missing=%d", len(prov_rows), missing)
        return written

    def add_relationships_batch(
        self,
        rows: list[tuple[int, int, str]],
        full_rebuild: bool = False,
    ) -> None:
        """Batch-upsert relationship edges in one Oracle round-trip.

        Each row: (source_id, target_id, name).

        full_rebuild — see add_entities_batch's docstring: switches
        merge_graph_edge (MERGE) to insert_graph_edge (plain INSERT),
        valid only for project_graph()'s clear()-then-rewrite path. The
        RDB's aryx_relationship table has no uniqueness constraint on
        (source, target, name) — MERGE silently absorbs an accidental
        duplicate edge (a no-op re-match), but a plain INSERT would raise
        ORA-00001 on one, so duplicates are deduplicated here first
        (same (ws, src, tgt, name)-keyed pattern add_entities_batch
        already uses for entity ids).
        """
        if not rows:
            return
        logger.info("graph edges batch start count=%d", len(rows))
        if full_rebuild:
            seen: dict[tuple, dict] = {}
            for src, tgt, name in rows:
                seen[(self._workspace_id, src, tgt, name)] = {
                    "ws": self._workspace_id, "src": src, "tgt": tgt, "name": name,
                }
            batch = list(seen.values())
        else:
            batch = [
                {"ws": self._workspace_id, "src": src, "tgt": tgt, "name": name}
                for src, tgt, name in rows
            ]
        chunks = list(_iter_chunks(batch, payload_key="name"))
        query_name = "insert_graph_edge" if full_rebuild else "merge_graph_edge"
        self._write_chunks(chunks, query_name, on_batch=None)
        logger.info("graph edges batch done count=%d", len(rows))
