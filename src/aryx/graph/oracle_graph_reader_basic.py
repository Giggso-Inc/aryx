"""Basic single-entity/type-listing reads, mixed into OracleGraphReader.

Split out of `graph/oracle_graph_reader.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import re
from typing import Any

from aryx.config import get_settings
from aryx.graph.oracle_graph_reader_helpers import _entity, _parse_attrs

_ATTR_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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

    def count_entities(self, ontology_type: str | None = None) -> int:
        """True entity count (optionally scoped to one type) — never capped.

        CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T11: callers that only need
        a count were doing len(find_entities(limit=500)), silently
        under-reporting any workspace with more than 500 entities.
        """
        with self._connection() as conn:
            with conn.cursor() as cur:
                if ontology_type:
                    cur.execute(
                        "SELECT COUNT(*) FROM aryx_graph_vertex "
                        "WHERE workspace_id = :1 AND type = :2",
                        (self._workspace_id, ontology_type),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM aryx_graph_vertex WHERE workspace_id = :1",
                        (self._workspace_id,),
                    )
                row = cur.fetchone()
        return int(row[0]) if row else 0

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
                      name: str | None = None, attrs: dict[str, Any] | None = None,
                      limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Find entities filtered by type, case-insensitive name substring,
        and/or JSON attribute values.

        Args:
            ontology_type: Exact ontology type to match, or None for any.
            name: Substring matched case-insensitively against the name, or None.
            attrs: {key: value} matched case-insensitively against the
                entity's JSON `attributes` column, ANDed with type/name —
                mirrors GraphReader.find_entities' own attrs= contract.
                Keys are validated against ^[A-Za-z_][A-Za-z0-9_]*$ and
                rejected otherwise (raises ValueError): Oracle's JSON_VALUE
                path expression must be a compile-time literal (ORA-40454
                on a bind variable), so the key is embedded directly into
                the SQL text rather than bound — the same reasoning
                Cypher's e.{key} interpolation already documents for
                property names, values still bound. See docs/oci-oracle/
                DEV_RV_MSI_INTO_DEV_OCI_INTEGRATION_PLAN_2026-09-21.md's
                Part B for why the originally-planned '$.' || :key_N
                bind-the-path approach doesn't work.
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
        if attrs:
            for i, (key, value) in enumerate(attrs.items()):
                if not _ATTR_KEY_RE.fullmatch(key):
                    raise ValueError(f"find_entities: invalid attribute key {key!r}")
                pname = f"attr_val_{i}"
                clauses.append(
                    f"LOWER(JSON_VALUE(attributes, '$.{key}')) "  # nosec S608 — key validated above
                    f"LIKE '%' || LOWER(:{pname}) || '%'"
                )
                params[pname] = value
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
