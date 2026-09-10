"""Batch write methods for the Oracle Property Graph writer — one Oracle
round-trip per phase, mixed into OracleGraphStore.

Split out of `graph/oracle_graph_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
from typing import Callable

from aryx.graph.oracle_graph_store_helpers import _display_name, _iter_chunks, _safe_attrs_json
from aryx.queries import load

logger = logging.getLogger(__name__)


class _OracleGraphBatchMixin:
    """Batch methods — one Oracle round-trip per phase, mixed into OracleGraphStore."""

    def add_entities_batch(
        self,
        rows: list[tuple[int, str, dict, list | None, str | None]],
        on_batch: "Callable[[int], None] | None" = None,
    ) -> int:
        """Batch-upsert entity vertices in Oracle round-trips, one per chunk.

        Each row: (entity_id, ontology_type, attributes, labels, iri).
        ``labels`` is accepted for API parity with add_entity but not stored
        (Oracle backing table has no labels column).

        on_batch — optional callback invoked with the running total of rows
        written after each executemany chunk, for sub-progress reporting
        (mirrors FalkorGraphStore.add_entities_batch).
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
        written = 0
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for chunk in _iter_chunks(batch, payload_key="attrs"):
                    cur.executemany(load("merge_graph_vertex"), chunk)
                    written += len(chunk)
                    logger.info("graph vertices chunk rows=%d done", len(chunk))
                    if on_batch is not None:
                        on_batch(written)
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
    ) -> None:
        """Batch-upsert relationship edges in one Oracle round-trip.

        Each row: (source_id, target_id, name).
        """
        if not rows:
            return
        logger.info("graph edges batch start count=%d", len(rows))
        batch = [
            {"ws": self._workspace_id, "src": src, "tgt": tgt, "name": name}
            for src, tgt, name in rows
        ]
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for i, chunk in enumerate(_iter_chunks(batch, payload_key="name")):
                    cur.executemany(load("merge_graph_edge"), chunk)
                    logger.info("graph edges chunk=%d rows=%d done", i + 1, len(chunk))
        logger.info("graph edges batch done count=%d", len(rows))
