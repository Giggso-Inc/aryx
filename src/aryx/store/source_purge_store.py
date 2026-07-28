"""Atomic, source-scoped deletion and survivor repair."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Json

from aryx.queries import load, split_statements
from aryx.resolution.golden import golden_record_with_policy
from aryx.resolution.survivorship import SurvivorshipPolicy
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)


class SourcePurgeBusy(RuntimeError):
    """Raised when ingestion is active in the target workspace."""


@dataclass(frozen=True)
class CatalogUpdate:
    """Datasource catalog mutation committed with the source purge."""

    datasource_id: int
    name: str
    kind: str
    config: dict[str, Any]


@dataclass(frozen=True)
class SurvivorState:
    """Rebuilt golden-record state for one impacted surviving entity."""

    attributes: dict[str, Any]
    confidence: float
    conflicts: list[dict[str, Any]]


def _policy(raw: dict[str, Any] | None) -> SurvivorshipPolicy:
    if raw:
        return SurvivorshipPolicy.from_json(raw)
    return SurvivorshipPolicy(default_strategy="most_complete")


def rebuild_survivor_states(
    rows: list[tuple[int, int, dict[str, Any] | str, str | None, Any]],
    policy_data: dict[str, Any] | None,
) -> dict[int, SurvivorState]:
    """Rebuild impacted entities from their remaining landed records."""
    members_by_entity: dict[int, list[dict[str, Any]]] = {}
    for entity_id, record_id, payload, source_system, cleaned_at in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        members_by_entity.setdefault(int(entity_id), []).append({
            "payload": payload or {},
            "record_id": int(record_id),
            "source_system": source_system,
            "cleaned_at": cleaned_at,
        })

    policy = _policy(policy_data)
    states: dict[int, SurvivorState] = {}
    for entity_id, members in members_by_entity.items():
        members.sort(key=lambda member: member["record_id"])
        attributes, _provenance, conflicts = golden_record_with_policy(
            members,
            policy,
        )
        states[entity_id] = SurvivorState(
            attributes=attributes,
            confidence=0.5,
            conflicts=conflicts,
        )
    return states


class SourcePurgeStore:
    """Own the relational transaction for physical source deletion."""

    def __init__(self, dsn: str, workspace_id: int = 1) -> None:
        self._pool = get_pool(dsn)
        self._ws = int(workspace_id)

    @staticmethod
    def _rowcount(cursor: Any) -> int:
        return max(int(cursor.rowcount or 0), 0)

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

    def _repair_entities(
        self,
        cursor: Any,
        impacted_ids: list[int],
    ) -> tuple[list[int], int]:
        if not impacted_ids:
            return [], 0
        params = {"workspace_id": self._ws, "entity_ids": impacted_ids}
        cursor.execute(load("select_impacted_orphan_entity_ids"), params)
        orphan_ids = sorted(int(row[0]) for row in cursor.fetchall())

        cursor.execute(load("select_impacted_survivor_members"), params)
        member_rows = cursor.fetchall()
        cursor.execute(load("select_workspace_survivorship"), (self._ws,))
        policy_row = cursor.fetchone()
        policy_data = policy_row[0] if policy_row else {}
        if isinstance(policy_data, str):
            policy_data = json.loads(policy_data)
        states = rebuild_survivor_states(member_rows, policy_data)

        update_rows = [
            (
                Json(state.attributes),
                state.confidence,
                entity_id,
                self._ws,
            )
            for entity_id, state in sorted(states.items())
        ]
        if update_rows:
            cursor.executemany(load("repair_entity_after_source_purge"), update_rows)

        conflict_rows = [
            (
                self._ws,
                entity_id,
                conflict["attribute"],
                Json(conflict["winning_value"]),
                Json(conflict["losing_values"]),
                conflict["strategy"],
            )
            for entity_id, state in sorted(states.items())
            for conflict in state.conflicts
        ]
        if conflict_rows:
            cursor.executemany(load("insert_attribute_conflict"), conflict_rows)

        if orphan_ids:
            cursor.execute(load("delete_impacted_entities"), {
                "workspace_id": self._ws,
                "entity_ids": orphan_ids,
            })
        return orphan_ids, len(states)

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
                if statement.upper().startswith("DELETE FROM ARYX_RUN "):
                    runs_deleted += self._rowcount(cursor)
        return runs_deleted

    def _mutate_catalog(
        self,
        cursor: Any,
        delete_ids: list[int],
        update: CatalogUpdate | None,
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

    def purge(
        self,
        refs: list[tuple[str, str]] | tuple[tuple[str, str], ...],
        *,
        catalog_delete_ids: list[int] | None = None,
        catalog_update: CatalogUpdate | None = None,
    ) -> dict[str, Any]:
        """Purge source data and mutate its catalog in one transaction."""
        unique_refs = sorted({(str(system), str(dataset)) for system, dataset in refs})
        delete_ids = sorted({int(value) for value in (catalog_delete_ids or [])})
        with self._pool.connection() as conn:
            with conn.cursor() as cursor:
                self._lock_and_check_jobs(cursor)
                impacted_ids = self._impacted_ids(cursor, unique_refs)
                invalidated = self._invalidate_impacted(cursor, impacted_ids)
                landed_deleted, members_deleted = self._delete_source_rows(
                    cursor,
                    unique_refs,
                )
                orphan_ids, survivors_rebuilt = self._repair_entities(
                    cursor,
                    impacted_ids,
                )
                runs_deleted = self._cleanup_runs(cursor, unique_refs)
                cursor.execute(load("invalidate_projection_state"), (self._ws,))
                catalog_rows_deleted = self._mutate_catalog(
                    cursor,
                    delete_ids,
                    catalog_update,
                )

        logger.info(
            "source purge committed ws=%s refs=%d impacted=%d deleted=%d survivors=%d",
            self._ws,
            len(unique_refs),
            len(impacted_ids),
            len(orphan_ids),
            survivors_rebuilt,
        )
        return {
            "sources_purged": len(unique_refs),
            "landed_records_deleted": landed_deleted,
            "members_deleted": members_deleted,
            "entities_impacted": len(impacted_ids),
            "entities_deleted": len(orphan_ids),
            "survivors_rebuilt": survivors_rebuilt,
            "runs_deleted": runs_deleted,
            "catalog_rows_deleted": catalog_rows_deleted,
            "entity_ids_deleted": orphan_ids,
            **invalidated,
        }
