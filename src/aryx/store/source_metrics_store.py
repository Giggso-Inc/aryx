"""Database-side aggregates for scalable source catalog views."""
from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Json

from aryx.queries import load
from aryx.store.pool import get_pool


class SourceMetricsStore:
    """Read bounded source counts without materializing provenance rows."""

    def __init__(self, dsn: str, workspace_id: int) -> None:
        """Bind the aggregate reader to one workspace and shared pool."""
        self._pool = get_pool(dsn)
        self._ws = int(workspace_id)

    def source_record_counts(self) -> dict[tuple[str, str], int]:
        """Return resolved member counts grouped by physical source dataset."""
        rows = self._all("select_workspace_source_counts", {"workspace_id": self._ws})
        return {(str(row[0]), str(row[1])): int(row[2]) for row in rows}

    def source_entity_type_counts(
        self, source_map: list[tuple[str, str, str]],
    ) -> dict[str, list[tuple[str, int]]]:
        """Count distinct entities by logical source and ontology type."""
        if not source_map:
            return {}
        payload = [
            {"source_key": key, "source_system": system, "source_dataset": dataset}
            for key, system, dataset in dict.fromkeys(source_map)
        ]
        rows = self._all("select_source_entity_type_counts", {
            "workspace_id": self._ws,
            "source_map": Json(payload),
        })
        stats: dict[str, list[tuple[str, int]]] = {}
        for source_key, ontology_type, count in rows:
            stats.setdefault(str(source_key), []).append((str(ontology_type), int(count)))
        return stats

    def workspace_summary(self) -> dict[str, Any]:
        """Return the legacy DataSummary shape from aggregate queries."""
        types = [(str(row[0]), int(row[1])) for row in self._all(
            "select_workspace_entity_type_counts", {"workspace_id": self._ws},
        )]
        sources = self.source_record_counts()
        total_entities = sum(count for _name, count in types)
        source_records = sum(sources.values())
        return {
            "total_entities": total_entities,
            "type_count": len(types),
            "types": [{"name": name, "count": count} for name, count in types],
            "sources": [{"source": f"{system}.{dataset}", "count": count}
                        for (system, dataset), count in sources.items()],
            "source_records": source_records,
            "duplicates_merged": max(0, source_records - total_entities),
        }

    def source_records_page(
        self, system: str, dataset: str, *, limit: int, offset: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Return one bounded page of landed payloads for a physical source."""
        params = {"workspace_id": self._ws, "source_system": system, "source_dataset": dataset}
        total_row = self._one("count_landed_by_source", params)
        rows = self._all("select_landed_by_source_page", {
            **params, "limit": int(limit), "offset": int(offset),
        })
        payloads = [self._payload(row[1]) for row in rows]
        return int(total_row[0]) if total_row else 0, payloads

    def _all(self, query: str, params: dict[str, Any]) -> list[tuple]:
        """Execute a named read query and return every aggregate row."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load(query), params)
            return list(cur.fetchall())

    def _one(self, query: str, params: dict[str, Any]) -> tuple | None:
        """Execute a named read query and return its first aggregate row."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load(query), params)
            return cur.fetchone()

    @staticmethod
    def _payload(payload: Any) -> dict[str, Any]:
        """Normalize PostgreSQL and Oracle JSON payload representations."""
        if isinstance(payload, str):
            return json.loads(payload)
        return payload or {}
