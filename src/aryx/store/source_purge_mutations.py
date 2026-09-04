"""Per-step SQL mutations for the source-purge transaction, mixed into
SourcePurgeStore.

Split out of `store/source_purge_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). None of these methods call `get_pool` directly
(they use `self._pool`, set by `__init__` which stays in the hub with the
`aryx.store.source_purge_store.get_pool` patch target) — confirmed via
grep that this module carries zero patch risk of its own.
"""
from __future__ import annotations

import re
from typing import Any

from psycopg.types.json import Json

from aryx.queries import load, split_statements
from aryx.store.source_purge_helpers import CatalogUpdate, SourcePurgeBusy

_ARYX_RUN_DELETE_RE = re.compile(r"^\s*DELETE\s+FROM\s+ARYX_RUN\b", re.IGNORECASE)


class _SourcePurgeMutationsMixin:
    """Per-step SQL mutations, mixed into SourcePurgeStore."""

    def _lock_and_check_jobs(self, cursor: Any) -> None:
        cursor.execute(load("lock_workspace_for_mutation"), (self._ws,))
        if cursor.fetchone() is None:
            raise ValueError(f"workspace {self._ws} not found")
        cursor.execute(load("select_active_workspace_job"), (self._ws,))
        active = cursor.fetchone()
        if active:
            raise SourcePurgeBusy(
                f"ingestion job {active[0]} is {active[1]} in workspace {self._ws}"
            )

    def _impacted_ids(
        self,
        cursor: Any,
        refs: list[tuple[str, str]],
    ) -> list[int]:
        impacted: set[int] = set()
        for source_system, source_dataset in refs:
            cursor.execute(load("select_source_impacted_entity_ids"), {
                "workspace_id": self._ws,
                "source_system": source_system,
                "source_dataset": source_dataset,
            })
            impacted.update(int(row[0]) for row in cursor.fetchall())
        return sorted(impacted)

    def _invalidate_impacted(
        self,
        cursor: Any,
        impacted_ids: list[int],
    ) -> dict[str, int]:
        if not impacted_ids:
            return {
                "relationships_invalidated": 0,
                "conflicts_replaced": 0,
                "violations_invalidated": 0,
            }
        params = {"workspace_id": self._ws, "entity_ids": impacted_ids}
        counts: dict[str, int] = {}
        for query_name, result_name in (
            ("delete_impacted_relationships", "relationships_invalidated"),
            ("delete_impacted_projected_entities", "projected_entities_invalidated"),
            ("delete_impacted_attribute_conflicts", "conflicts_replaced"),
            ("delete_impacted_axiom_violations", "violations_invalidated"),
        ):
            cursor.execute(load(query_name), params)
            counts[result_name] = self._rowcount(cursor)
        return counts

    def _delete_source_rows(
        self,
        cursor: Any,
        refs: list[tuple[str, str]],
    ) -> tuple[int, int]:
        landed_deleted = 0
        members_deleted = 0
        for source_system, source_dataset in refs:
            params = {
                "workspace_id": self._ws,
                "source_system": source_system,
                "source_dataset": source_dataset,
            }
            cursor.execute(load("delete_source_entity_members"), params)
            members_deleted += self._rowcount(cursor)
            cursor.execute(load("delete_source_landed_records"), params)
            landed_deleted += self._rowcount(cursor)
        return landed_deleted, members_deleted

    def _cleanup_runs(
        self,
        cursor: Any,
        refs: list[tuple[str, str]],
    ) -> int:
        runs_deleted = 0
        statements = split_statements(load("purge_source_run_data"))
        for source_system, source_dataset in refs:
            params = {
                "workspace_id": self._ws,
                "source_system": source_system,
                "source_dataset": source_dataset,
            }
            for statement in statements:
                cursor.execute(statement, params)
                if _ARYX_RUN_DELETE_RE.match(statement):
                    runs_deleted += self._rowcount(cursor)
        return runs_deleted

    def _mutate_catalog(
        self,
        cursor: Any,
        delete_ids: list[int],
        update: "CatalogUpdate | None",
    ) -> int:
        if update is not None:
            cursor.execute(load("update_datasource"), {
                "id": update.datasource_id,
                "name": update.name,
                "kind": update.kind,
                "config_json": Json(update.config),
                "secret_cipher": None,
                "secret_mask": None,
            })
            if cursor.fetchone() is None:
                raise ValueError(f"datasource {update.datasource_id} not found")
        for datasource_id in delete_ids:
            cursor.execute(
                load("delete_datasource_row"),
                {"id": int(datasource_id)},
            )
        return len(delete_ids)
