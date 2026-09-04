"""Table-partition lifecycle + purge/nuke/delete for workspaces.

Split out of `workspaces.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg import sql

from aryx.queries import load, split_statements

logger = logging.getLogger(__name__)

_PARTITIONED = ["aryx_landed_record", "aryx_entity", "aryx_entity_member", "aryx_relationship"]


class _WorkspacePartitionsMixin:
    """Partition attach/drop + purge_data/delete, mixed into WorkspaceStore.

    `nuke()` and `_drop_partitions_with_conn` stay in the hub instead:
    `tests/test_workspaces.py` does `patch.object(workspaces, "load", ...)`,
    which only rebinds the hub module's own attribute — `nuke()` (and the
    helper it calls) must resolve `load` from that same namespace to see
    the patch.
    """

    def _attach_partitions(self, wid: int) -> None:
        template = load("create_partition")
        with self._pool.connection() as conn:
            for base in _PARTITIONED:
                conn.execute(sql.SQL(template).format(
                    child=sql.Identifier(f"{base}_ws{wid}"),
                    parent=sql.Identifier(base), wid=sql.Literal(wid)))

    def _drop_partitions(self, wid: int) -> None:
        with self._pool.connection() as conn:
            self._drop_partitions_with_conn(conn, wid)

    def purge_data(self, wid: int) -> dict[str, Any]:
        """Truncate partition children + delete non-partitioned rows by wid."""
        wid = int(wid)
        truncate_template = load("truncate_partition")
        with self._pool.connection() as conn:
            for base in _PARTITIONED:
                child = f"{base}_ws{wid}"
                existing = {
                    str(row[0])
                    for row in conn.execute(
                        load("select_partition_children"),
                        {"parent": base},
                    ).fetchall()
                }
                if child in existing:
                    conn.execute(
                        sql.SQL(truncate_template).format(
                            child=sql.Identifier(child),
                        )
                    )
            for statement in split_statements(load("purge_workspace_data")):
                conn.execute(statement, {"wid": wid})
            conn.execute(load("reset_workspace_context"), {"wid": wid})
        logger.info("workspace purged id=%s", wid)
        return {"status": "purged", "workspace_id": wid}

    def delete(self, wid: int) -> None:
        """Physically purge a workspace: drop partitions + its run/job rows."""
        if int(wid) == 1:
            raise ValueError("the Default workspace cannot be deleted")
        self._drop_partitions(int(wid))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("delete_profiles_by_workspace"), (wid,))
                cur.execute(load("delete_tags_by_workspace"), (wid,))
                cur.execute(load("delete_runs_by_workspace"), (wid,))
                cur.execute(load("delete_jobs_by_workspace"), (wid,))
                cur.execute(load("delete_workspace_row"), (wid,))
        logger.info("workspace deleted id=%s", wid)
