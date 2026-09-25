"""Oracle Property Graph writer — stores entities/relationships in ADB 26ai backing tables.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`oracle_graph_store_helpers.py` (attr sanitization, chunking, display-name
extraction) and `oracle_graph_store_batch.py` (the three batch write
methods, mixed in as `_OracleGraphBatchMixin`). Zero whitebox test
patches exist anywhere against `aryx.graph.oracle_graph_store.*`
(confirmed via grep), so the split was purely mechanical.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.graph.oracle_graph_store_batch import _OracleGraphBatchMixin
from aryx.graph.oracle_graph_store_helpers import _display_name, _safe_attrs_json
from aryx.queries import load

logger = logging.getLogger(__name__)

__all__ = ["OracleGraphStore"]


class OracleGraphStore(_OracleGraphBatchMixin):
    """Writes entity / provenance / relationship data to Oracle ADB 26ai backing tables."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        """Connect to Oracle pool and scope all writes to workspace_id."""
        from aryx.store.oracle_pool import get_oracle_pool
        self._pool = get_oracle_pool(dsn)
        self._workspace_id = workspace_id

    def clear(self) -> None:
        """Delete all graph data for this workspace."""
        logger.info("graph clear ws=%s — deleting provenance", self._workspace_id)
        with self._pool.connection() as conn:
            conn.execute(load("delete_graph_provenance_by_workspace"), (self._workspace_id,))
            logger.info("graph clear ws=%s — deleting edges", self._workspace_id)
            conn.execute(load("delete_graph_edge_by_workspace"), (self._workspace_id,))
            logger.info("graph clear ws=%s — deleting sources", self._workspace_id)
            conn.execute(load("delete_graph_source_by_workspace"), (self._workspace_id,))
            logger.info("graph clear ws=%s — deleting vertices", self._workspace_id)
            conn.execute(load("delete_graph_vertex_by_workspace"), (self._workspace_id,))
        logger.info("graph clear ws=%s — done", self._workspace_id)

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
                    "attrs": _safe_attrs_json(attributes),
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

    def remove_entities_by_type(self, ontology_type: str) -> None:
        """Delete every entity vertex of a type, their edges, and their
        provenance links -- the Oracle-graph counterpart of FalkorStore's
        method of the same name.

        CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T9/T11 follow-up
        (confirmed live, 2026-09-25): ontology_api.py::delete_type()
        unconditionally instantiated FalkorStore for this cascade step
        regardless of ARYX_GRAPH_BACKEND -- the same "assumes FalkorDB
        everywhere" pattern already fixed once for admin_api.py::
        rebuild_graph() (see that commit). On this OCI/Oracle Graph
        deployment there is no FalkorDB to connect to at all, so every
        DELETE /ontology/types/{name} call failed here even after the
        RDB-side fetchall() bug (same endpoint, different cause) was fixed.
        """
        params = {"ws": self._workspace_id, "typ": ontology_type}
        with self._pool.connection() as conn:
            conn.execute(load("delete_graph_provenance_by_type"), params)
            conn.execute(load("delete_graph_edge_by_type"), params)
            conn.execute(load("delete_graph_vertex_by_type"), params)

    def add_relationship(self, source_id: int, target_id: int, name: str) -> None:
        """Add a directed relationship edge between two entities."""
        with self._pool.connection() as conn:
            conn.execute(
                load("merge_graph_edge"),
                {"ws": self._workspace_id, "src": source_id, "tgt": target_id, "name": name},
            )
