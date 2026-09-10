"""Atomic, source-scoped deletion and survivor repair.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`source_purge_helpers.py` (result dataclasses + `rebuild_survivor_states`)
and `source_purge_mutations.py` (`_SourcePurgeMutationsMixin`, the
per-step SQL mutations), both re-imported here. `get_pool` is called only
in `__init__`, which stays here with the class definition — the one
patch on this module (`aryx.store.source_purge_store.get_pool`, from
`tests/test_source_purge_store.py`) is unaffected by moving everything
else out, confirmed via grep that no other method calls `get_pool`
directly.
"""
from __future__ import annotations

import logging
from typing import Any

from aryx.queries import load
from aryx.store.pool import get_pool
from aryx.store.source_purge_helpers import (
    CatalogUpdate,
    SourcePurgeBusy,
    SurvivorState,
    rebuild_survivor_states,
)
from aryx.store.source_purge_mutations import _SourcePurgeMutationsMixin
from aryx.store.source_purge_repair import _SourcePurgeRepairMixin

__all__ = [
    "CatalogUpdate",
    "SourcePurgeBusy",
    "SourcePurgeStore",
    "SurvivorState",
    "rebuild_survivor_states",
]

logger = logging.getLogger(__name__)


class SourcePurgeStore(_SourcePurgeMutationsMixin, _SourcePurgeRepairMixin):
    """Own the relational transaction for physical source deletion."""

    def __init__(self, dsn: str, workspace_id: int = 1) -> None:
        self._pool = get_pool(dsn)
        self._ws = int(workspace_id)

    @staticmethod
    def _rowcount(cursor: Any) -> int:
        return max(int(cursor.rowcount or 0), 0)

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
