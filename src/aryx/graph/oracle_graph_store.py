"""Oracle Property Graph writer — stores entities/relationships in ADB 23ai backing tables."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_NAME_KEYS = ("name", "full_name", "title", "label", "ticket_ref", "ref",
              "sku", "code", "email", "username")


def _display_name(attributes: dict[str, Any]) -> str:
    for key in _NAME_KEYS:
        value = attributes.get(key)
        if value:
            return str(value)
    for value in attributes.values():
        if isinstance(value, str) and 0 < len(value) <= 80:
            return value
    return ""


class OracleGraphStore:
    """Writes entity / provenance / relationship data to Oracle ADB 23ai backing tables."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        from aryx.store.oracle_pool import get_oracle_pool
        self._pool = get_oracle_pool(dsn)
        self._workspace_id = workspace_id

    def clear(self) -> None:
        """Delete all graph data for this workspace."""
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM aryx_graph_provenance WHERE workspace_id = :1",
                (self._workspace_id,),
            )
            conn.execute(
                "DELETE FROM aryx_graph_edge WHERE workspace_id = :1",
                (self._workspace_id,),
            )
            conn.execute(
                "DELETE FROM aryx_graph_source WHERE workspace_id = :1",
                (self._workspace_id,),
            )
            conn.execute(
                "DELETE FROM aryx_graph_vertex WHERE workspace_id = :1",
                (self._workspace_id,),
            )

    def add_entity(self, entity_id: int, ontology_type: str,
                   attributes: dict[str, Any],
                   labels: list[str] | None = None,
                   iri: str | None = None) -> None:
        """Upsert an entity vertex into the backing table."""
        name = _display_name(attributes) or f"#{entity_id}"
        attrs_json = json.dumps(attributes)
        with self._pool.connection() as conn:
            conn.execute(
                """
                MERGE INTO aryx_graph_vertex t
                USING (SELECT :ws AS workspace_id, :eid AS entity_id FROM dual) s
                ON (t.workspace_id = s.workspace_id AND t.entity_id = s.entity_id)
                WHEN MATCHED THEN
                    UPDATE SET t.type = :typ, t.name = :name,
                               t.iri = :iri, t.attributes = :attrs
                WHEN NOT MATCHED THEN
                    INSERT (workspace_id, entity_id, type, name, iri, attributes)
                    VALUES (:ws, :eid, :typ, :name, :iri, :attrs)
                """,
                {
                    "ws": self._workspace_id,
                    "eid": entity_id,
                    "typ": ontology_type,
                    "name": name,
                    "iri": iri or "",
                    "attrs": attrs_json,
                },
            )

    def add_provenance(self, entity_id: int, system: str, dataset: str,
                       record_id: str) -> None:
        """Link an entity to its source record."""
        with self._pool.connection() as conn:
            # Upsert source row
            conn.execute(
                """
                MERGE INTO aryx_graph_source t
                USING (SELECT :ws AS workspace_id, :sys AS system,
                              :ds AS dataset, :rid AS record_id FROM dual) s
                ON (t.workspace_id = s.workspace_id
                    AND t.system = s.system
                    AND t.dataset = s.dataset
                    AND t.record_id = s.record_id)
                WHEN NOT MATCHED THEN
                    INSERT (workspace_id, system, dataset, record_id)
                    VALUES (:ws, :sys, :ds, :rid)
                """,
                {"ws": self._workspace_id, "sys": system, "ds": dataset, "rid": record_id},
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT source_id FROM aryx_graph_source "
                    "WHERE workspace_id = :1 AND system = :2 "
                    "AND dataset = :3 AND record_id = :4",
                    (self._workspace_id, system, dataset, record_id),
                )
                row = cur.fetchone()
            if not row:
                return
            source_id = row[0]
            conn.execute(
                """
                MERGE INTO aryx_graph_provenance t
                USING (SELECT :ws AS workspace_id, :eid AS entity_id,
                              :sid AS source_id FROM dual) s
                ON (t.workspace_id = s.workspace_id
                    AND t.entity_id = s.entity_id
                    AND t.source_id = s.source_id)
                WHEN NOT MATCHED THEN
                    INSERT (workspace_id, entity_id, source_id)
                    VALUES (:ws, :eid, :sid)
                """,
                {"ws": self._workspace_id, "eid": entity_id, "sid": source_id},
            )

    def remove_entity(self, entity_id: int) -> None:
        """Delete one entity vertex and its provenance links."""
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM aryx_graph_provenance "
                "WHERE workspace_id = :1 AND entity_id = :2",
                (self._workspace_id, entity_id),
            )
            conn.execute(
                "DELETE FROM aryx_graph_edge "
                "WHERE workspace_id = :1 AND (src_id = :2 OR tgt_id = :2)",
                (self._workspace_id, entity_id),
            )
            conn.execute(
                "DELETE FROM aryx_graph_vertex "
                "WHERE workspace_id = :1 AND entity_id = :2",
                (self._workspace_id, entity_id),
            )

    def add_relationship(self, source_id: int, target_id: int, name: str) -> None:
        """Add a directed relationship edge between two entities."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                MERGE INTO aryx_graph_edge t
                USING (SELECT :ws AS workspace_id, :src AS src_id,
                              :tgt AS tgt_id, :name AS name FROM dual) s
                ON (t.workspace_id = s.workspace_id
                    AND t.src_id = s.src_id
                    AND t.tgt_id = s.tgt_id
                    AND t.name = s.name)
                WHEN NOT MATCHED THEN
                    INSERT (workspace_id, src_id, tgt_id, name)
                    VALUES (:ws, :src, :tgt, :name)
                """,
                {"ws": self._workspace_id, "src": source_id,
                 "tgt": target_id, "name": name},
            )
