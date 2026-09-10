"""Basic single-entity/type-listing reads, mixed into OracleGraphReader.

Split out of `graph/oracle_graph_reader.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.graph.oracle_graph_reader_helpers import _entity, _parse_attrs


class _OracleGraphBasicReadMixin:
    """get_entity / distinct_types / describe_schema / find_entities, mixed into OracleGraphReader."""

    def get_entity(self, entity_id: int) -> dict[str, Any] | None:
        """Return {id, type, name, attributes} for one entity, or None if not in this workspace."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT entity_id, type, name, attributes FROM aryx_graph_vertex "
                    "WHERE workspace_id = :1 AND entity_id = :2",
                    (self._workspace_id, entity_id),
                )
                row = cur.fetchone()
        return _entity(row) if row else None

    def distinct_types(self) -> list[str]:
        """Every distinct entity type in this workspace — deterministic, no sampling."""
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT type FROM aryx_graph_vertex "
                    "WHERE workspace_id = :1 ORDER BY type",
                    (self._workspace_id,),
                )
                return [r[0] for r in cur.fetchall() if r[0]]

    def describe_schema(self, sample_per_type: int = 25) -> dict[str, Any]:
        """Describe the actual stored schema for query generation (port parity).

        Mirrors GraphReader.describe_schema: entity types, relationship names,
        and observed attribute keys per type (sampled from the JSON column).
        """
        types = self.distinct_types()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT name FROM aryx_graph_edge "
                    "WHERE workspace_id = :1 ORDER BY name",
                    (self._workspace_id,),
                )
                rel_names = [r[0] for r in cur.fetchall() if r[0]]
                props_by_type: dict[str, list[str]] = {}
                for t in types:
                    cur.execute(
                        "SELECT attributes FROM aryx_graph_vertex "
                        "WHERE workspace_id = :1 AND type = :2 "
                        "FETCH FIRST :3 ROWS ONLY",
                        (self._workspace_id, t, max(1, int(sample_per_type))),
                    )
                    keys: set[str] = set()
                    for (raw,) in cur.fetchall():
                        keys.update(_parse_attrs(raw).keys())
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
        """Find entities filtered by type and/or case-insensitive name substring.

        Args:
            ontology_type: Exact ontology type to match, or None for any.
            name: Substring matched case-insensitively against the name, or None.
            limit: Maximum rows to return (coerced to int, capped at ARYX_GRAPH_QUERY_LIMIT).
            offset: Rows to skip before applying limit — see GraphReader.find_entities.

        Returns:
            A list of {id, type, name, attributes} dicts.
        """
        clauses: list[str] = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": self._workspace_id}
        if ontology_type:
            clauses.append("type = :typ")
            params["typ"] = ontology_type
        if name:
            clauses.append("LOWER(name) LIKE '%' || LOWER(:name) || '%'")
            params["name"] = name
        where = " AND ".join(clauses)
        capped = max(1, min(int(limit), get_settings().graph_query_limit))
        skip = max(0, int(offset))
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT entity_id, type, name, attributes FROM aryx_graph_vertex "
                    f"WHERE {where} ORDER BY entity_id "
                    f"OFFSET {skip} ROWS FETCH NEXT {capped} ROWS ONLY",  # nosec S608 — capped/skip are validated ints
                    params,
                )
                rows = cur.fetchall()
        return [_entity(r) for r in rows]
