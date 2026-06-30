"""Oracle Property Graph writer — stores entities/relationships in ADB 23ai backing tables."""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.queries import load

logger = logging.getLogger(__name__)

_NAME_KEYS = ("name", "full_name", "title", "label", "ticket_ref", "ref",
              "sku", "code", "email", "username", "_text")

# Oracle ADB thin-client ORA-03106 guard values.
# Trigger is num_rows × num_bind_params, not just total bytes.
# merge_graph_vertex has 6 bind vars → 25 rows = 150 bind slots per call.
# Keep attrs small so even 25 rows stay well under the SDU budget.
_CHUNK_MAX_ROWS = 25
_CHUNK_MAX_BYTES = 50_000

# Graph projection attrs — display + traversal only, not source of truth.
# Full attribute text lives in aryx_entity.attributes (the primary store).
_GRAPH_ATTR_STR_MAX = 200


def _safe_attrs_json(attrs: dict[str, Any]) -> str:
    """Serialize attrs, always truncating long string values to _GRAPH_ATTR_STR_MAX chars.

    The graph store is a projection cache — full text lives in aryx_entity.attributes.
    CPQ function bodies and scripts cause ORA-03106 even across small row counts
    because each bind variable contributes to the wire-protocol packet size.
    Trim unconditionally so no single bind value is large.
    """
    trimmed = {
        k: (v[:_GRAPH_ATTR_STR_MAX] + "…" if isinstance(v, str) and len(v) > _GRAPH_ATTR_STR_MAX else v)
        for k, v in attrs.items()
    }
    return json.dumps(trimmed, default=str)


def _iter_chunks(batch: list[dict], payload_key: str = "attrs") -> list[list[dict]]:
    """Yield sub-lists bounded by row count AND estimated payload bytes.

    Prevents ORA-03106 when individual attribute JSON blobs are large
    (e.g. CPQ function bodies) even at low row counts.
    """
    chunk: list[dict] = []
    size = 0
    for row in batch:
        val = row.get(payload_key)
        row_bytes = len(val) if isinstance(val, (str, bytes)) else 0
        if chunk and (len(chunk) >= _CHUNK_MAX_ROWS or size + row_bytes > _CHUNK_MAX_BYTES):
            yield chunk
            chunk = []
            size = 0
        chunk.append(row)
        size += row_bytes
    if chunk:
        yield chunk


def _display_name(attributes: dict[str, Any]) -> str:
    """Extract a human-readable display name from entity attributes."""
    for key in _NAME_KEYS:
        value = attributes.get(key)
        if value:
            return str(value)
    for key, value in attributes.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and 0 < len(value) <= 80:
            return value
    return ""


class OracleGraphStore:
    """Writes entity / provenance / relationship data to Oracle ADB 23ai backing tables."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        """Connect to Oracle pool and scope all writes to workspace_id."""
        from aryx.store.oracle_pool import get_oracle_pool
        self._pool = get_oracle_pool(dsn)
        self._workspace_id = workspace_id

    def clear(self) -> None:
        """Delete all graph data for this workspace."""
        with self._pool.connection() as conn:
            conn.execute(load("delete_graph_provenance_by_workspace"), (self._workspace_id,))
            conn.execute(load("delete_graph_edge_by_workspace"), (self._workspace_id,))
            conn.execute(load("delete_graph_source_by_workspace"), (self._workspace_id,))
            conn.execute(load("delete_graph_vertex_by_workspace"), (self._workspace_id,))

    def add_entity(self, entity_id: int, ontology_type: str,
                   attributes: dict[str, Any],
                   labels: list[str] | None = None,
                   iri: str | None = None) -> None:
        """Upsert an entity vertex into the backing table."""
        name = _display_name(attributes) or f"#{entity_id}"
        with self._pool.connection() as conn:
            conn.execute(
                load("merge_graph_vertex"),
                {
                    "ws": self._workspace_id,
                    "eid": entity_id,
                    "typ": ontology_type,
                    "name": name,
                    "iri": iri or "",
                    "attrs": json.dumps(attributes),
                },
            )

    def add_provenance(self, entity_id: int, system: str, dataset: str,
                       record_id: str) -> None:
        """Link an entity to its source record."""
        with self._pool.connection() as conn:
            conn.execute(
                load("merge_graph_source"),
                {"ws": self._workspace_id, "sys": system, "ds": dataset, "rid": record_id},
            )
            with conn.cursor() as cur:
                cur.execute(
                    load("select_graph_source_id"),
                    (self._workspace_id, system, dataset, record_id),
                )
                row = cur.fetchone()
            if not row:
                return
            conn.execute(
                load("merge_graph_provenance"),
                {"ws": self._workspace_id, "eid": entity_id, "sid": row[0]},
            )

    def remove_entity(self, entity_id: int) -> None:
        """Delete one entity vertex and its provenance links."""
        with self._pool.connection() as conn:
            conn.execute(load("delete_graph_provenance_by_entity"),
                         (self._workspace_id, entity_id))
            conn.execute(load("delete_graph_edge_by_entity"),
                         (self._workspace_id, entity_id))
            conn.execute(load("delete_graph_vertex_by_entity"),
                         (self._workspace_id, entity_id))

    def add_relationship(self, source_id: int, target_id: int, name: str) -> None:
        """Add a directed relationship edge between two entities."""
        with self._pool.connection() as conn:
            conn.execute(
                load("merge_graph_edge"),
                {"ws": self._workspace_id, "src": source_id, "tgt": target_id, "name": name},
            )

    # ── Batch methods — one Oracle round-trip per phase ──────────────────────

    def add_entities_batch(
        self,
        rows: list[tuple[int, str, dict, list | None, str | None]],
    ) -> None:
        """Batch-upsert entity vertices in one Oracle round-trip.

        Each row: (entity_id, ontology_type, attributes, labels, iri).
        ``labels`` is accepted for API parity with add_entity but not stored
        (Oracle backing table has no labels column).
        """
        if not rows:
            return
        logger.info("graph vertices batch start count=%d", len(rows))
        batch = [
            {
                "ws": self._workspace_id,
                "eid": eid,
                "typ": typ,
                "name": _display_name(attrs) or f"#{eid}",
                "iri": iri or "",
                "attrs": _safe_attrs_json(attrs),
            }
            for eid, typ, attrs, _labels, iri in rows
        ]
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for chunk in _iter_chunks(batch, payload_key="attrs"):
                    cur.executemany(load("merge_graph_vertex"), chunk)
                    logger.info("graph vertices chunk rows=%d done", len(chunk))
        logger.info("graph vertices batch done count=%d", len(rows))

    def add_provenance_batch(
        self,
        rows: list[tuple[int, str, str, str]],
    ) -> None:
        """Batch-upsert provenance edges in three Oracle round-trips.

        Each row: (entity_id, system, dataset, record_id).

        Steps within one connection/transaction:
          1. executemany merge_graph_source   — upsert all source records
          2. SELECT source_id back for the workspace
          3. executemany merge_graph_provenance — link entity → source
        """
        if not rows:
            return
        logger.info("graph provenance batch start count=%d", len(rows))
        source_rows = [
            {"ws": self._workspace_id, "sys": system, "ds": dataset, "rid": record_id}
            for _eid, system, dataset, record_id in rows
        ]
        missing = 0
        prov_rows: list[dict] = []
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for chunk in _iter_chunks(source_rows, payload_key="rid"):
                    cur.executemany(load("merge_graph_source"), chunk)
                logger.info("graph sources merged count=%d — fetching source_ids", len(source_rows))
                cur.execute(
                    "SELECT source_id, system, dataset, record_id "
                    "FROM aryx_graph_source WHERE workspace_id = :1",
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
                    for chunk in _iter_chunks(prov_rows, payload_key="sid"):
                        cur.executemany(load("merge_graph_provenance"), chunk)
        logger.info("graph provenance batch done prov=%d missing=%d", len(prov_rows), missing)

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
                for chunk in _iter_chunks(batch, payload_key="name"):
                    cur.executemany(load("merge_graph_edge"), chunk)
        logger.info("graph edges batch done count=%d", len(rows))
