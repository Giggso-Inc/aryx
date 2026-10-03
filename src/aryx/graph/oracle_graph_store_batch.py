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
        should_stop: "Callable[[], bool] | None" = None,
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

        should_stop — checked at the top of each chunk (sequential) or in
        the as_completed drain loop (concurrent); on True, stops submitting
        further chunks and returns the count ACTUALLY written, following
        the established should_stop convention (dimension_link.py,
        enrich_relate_isolated.py): break, don't raise, keep whatever is
        already done. This matters here specifically because a cancelled
        job previously had no way to interrupt this loop at all — a 240MB
        XML's ~11,700-chunk vertex+edge write kept running to completion
        (tens of minutes) after "cancel" with zero effect, the exact gap
        this parameter closes. In the sequential branch, breaking (rather
        than raising) is required for correctness, not just convention: the
        pool's connection() context manager (oracle_connection_pool.py)
        commits on clean exit but rolls back the WHOLE transaction -- every
        chunk already executemany'd in this same connection, not just the
        one in flight -- on any exception, so raising here would silently
        discard already-committed-looking work instead of just stopping.

        In the concurrent branch, up to `workers` chunks can already be
        mid-executemany() when should_stop() is first observed True (they
        can't be force-killed mid-call, the same real limitation documented
        at every other should_stop call site in this codebase) -- those are
        explicitly drained and their rows counted below rather than
        dropped, so the returned total always reflects every row actually
        committed, never an undercount. Every remaining pending future is
        cancelled in one tight pass BEFORE waiting on any of the (hopefully
        few) that couldn't be -- not interleaved cancel-then-wait-then-
        cancel-then-wait, which would block on each already-running future
        in turn while idle workers keep dequeuing and starting MORE of the
        still-queued backlog in the meantime. Live-measured (PR #425
        review): an interleaved drain left 5-15% of an 11,700-chunk
        backlog running after "cancel" -- hundreds of chunks -- versus
        this two-pass version.
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
                    for i, chunk in enumerate(chunks):
                        if should_stop is not None and should_stop():
                            logger.warning(
                                "graph %s cancelled — stopping after %d/%d chunk(s), %d row(s) written",
                                query_name, i, len(chunks), written,
                            )
                            raven_log("WARN", "P3", "ingest.project.chunks_cancelled graph chunk write stopped by cancel",
                                      error_code="ARYX_ING_CANCELLED",
                                      context={"stage": "project", "query": query_name, "selected_option": "stop",
                                               "available_options": ["continue", "stop"], "reason_code": "SHOULD_STOP_TRUE",
                                               "chunks_done": i, "chunks_total": len(chunks), "rows_written": written})
                            break
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

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = [submit_ctx(pool, _write_one, chunk) for chunk in chunks]
            pending = set(futures)
            completed = 0
            for future in as_completed(futures):
                pending.discard(future)
                n = future.result()
                written += n
                completed += 1
                raven_log("DEBUG", "P4", "ingest.project.chunk_written graph chunk written",
                          context={"stage": "project", "query": query_name, "rows": n, "written_total": written,
                                   "elapsed_ms": int((time.monotonic() - _t0) * 1000)})
                logger.info("graph %s chunk rows=%d done", query_name, n)
                if on_batch is not None:
                    on_batch(written)
                if should_stop is not None and should_stop():
                    logger.warning(
                        "graph %s cancelled — stopping after %d/%d chunk(s) completed, %d row(s) written so far "
                        "(any already-running chunk still finishes and is counted below; no further queued "
                        "chunk starts)",
                        query_name, completed, len(futures), written,
                    )
                    raven_log("WARN", "P3", "ingest.project.chunks_cancelled graph chunk write stopped by cancel",
                              error_code="ARYX_ING_CANCELLED",
                              context={"stage": "project", "query": query_name, "selected_option": "stop",
                                       "available_options": ["continue", "stop"], "reason_code": "SHOULD_STOP_TRUE",
                                       "chunks_done": completed, "chunks_total": len(futures), "rows_written": written})
                    # Cancel EVERY pending future first, in one tight pass
                    # with no blocking call in the loop body -- then only
                    # wait on whichever ones couldn't be cancelled (already
                    # mid-executemany()). Doing this in two passes, not one
                    # (cancel-or-wait per future, interleaved), matters: a
                    # single interleaved pass that blocks on .result() for
                    # one still-running future gives every OTHER idle
                    # worker time to dequeue and start a NEXT queued chunk
                    # while we wait -- live-measured (PR #425 review) at
                    # 5-15% of the whole backlog still running after
                    # "cancel" with the interleaved version, versus ~2%
                    # before this should_stop support existed at all. The
                    # two-pass version cancels the entire queue before any
                    # worker can grab more of it.
                    running = [f for f in pending if not f.cancel()]
                    for f in running:
                        n = f.result()
                        written += n
                        completed += 1
                        logger.info("graph %s chunk rows=%d done (already running when cancelled)", query_name, n)
                    break
        finally:
            # cancel_futures=True here too: if a .result() above raised
            # (a real executemany failure, not just a cancel), any chunk
            # that didn't make it into `running` is still queued at this
            # point -- plain wait=True would let every one of those run to
            # completion before the exception propagates, defeating the
            # cancel for an unrelated reason. With cancel_futures=True this
            # drops them the same way the happy path already does, and
            # is a true no-op (nothing left to cancel) on the happy path
            # where draining above already completed normally.
            pool.shutdown(wait=True, cancel_futures=True)
        return written

    def add_entities_batch(
        self,
        rows: list[tuple[int, str, dict, list | None, str | None]],
        on_batch: "Callable[[int], None] | None" = None,
        full_rebuild: bool = False,
        should_stop: "Callable[[], bool] | None" = None,
    ) -> int:
        """Batch-upsert entity vertices in Oracle round-trips, one per chunk.

        Each row: (entity_id, ontology_type, attributes, labels, iri).
        ``labels`` is accepted for API parity with add_entity but not stored
        (Oracle backing table has no labels column).

        on_batch — optional callback invoked with the running total of rows
        written after each executemany chunk, for sub-progress reporting
        (mirrors FalkorGraphStore.add_entities_batch).

        should_stop — see ``_write_chunks``'s docstring; forwarded as-is.

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
        written = self._write_chunks(chunks, query_name, on_batch, should_stop=should_stop)
        logger.info("graph vertices batch done count=%d requested=%d", written, len(rows))
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
        should_stop: "Callable[[], bool] | None" = None,
    ) -> int:
        """Batch-upsert relationship edges in one Oracle round-trip.

        Each row: (source_id, target_id, name). Returns the count actually
        written (may be less than ``len(rows)`` after deduplication, or if
        should_stop fired partway through -- previously this returned None
        unconditionally, silently discarding the real count _write_chunks
        already computed).

        should_stop — see ``_write_chunks``'s docstring; forwarded as-is.

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
            return 0
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
        written = self._write_chunks(chunks, query_name, on_batch=None, should_stop=should_stop)
        logger.info("graph edges batch done count=%d requested=%d", written, len(rows))
        return written
