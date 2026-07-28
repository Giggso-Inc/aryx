"""Oracle ADB 23ai workspace store — replaces psycopg.connect() with oracledb."""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.queries import load, split_statements
from aryx.store.oracle_pool import OracleConnectionWrapper, get_oracle_pool

logger = logging.getLogger(__name__)

class OracleWorkspaceStore:
    """WorkspaceStore backed by Oracle ADB 23ai via oracledb.

    Matches the WorkspaceStore public API so call-sites need no changes.
    Postgres partition management (_attach_partitions / _drop_partitions) is
    replaced with no-ops — Oracle uses workspace_id as a plain indexed column.
    """

    def __init__(self, dsn: str) -> None:
        """Connect to Oracle ADB using the shared pool for the given DSN."""
        self._pool = get_oracle_pool(dsn)

    def close(self) -> None:
        """No-op — pool manages connection lifecycle."""
        pass  # pool manages connections

    # ── Partition stubs (no-op on Oracle) ─────────────────────────────────────
    def _attach_partitions(self, wid: int) -> None:
        """No-op — Oracle uses workspace_id as an indexed column, not list partitions."""
        pass  # Oracle uses workspace_id column; no partition DDL needed

    def _drop_partitions(self, wid: int) -> None:
        """Delete all rows for workspace wid from the four core tables."""
        with self._pool.connection() as conn:
            self._drop_partitions_with_conn(conn, wid)

    @staticmethod
    def _drop_partitions_with_conn(conn: Any, wid: int) -> None:
        with conn.cursor() as cur:
            for statement in split_statements(
                load("delete_workspace_partition_data")
            ):
                cur.execute(statement, {"wid": int(wid)})

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def create(self, name: str, description: str = "", context: str = "",
               brief: dict | None = None) -> dict[str, Any]:
        """Insert a new workspace row and return its full record."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("insert_workspace"),
                            (name, description, context, json.dumps(brief or {})))
                row = cur.fetchone()
        wid = int(row[0])
        logger.info("workspace created id=%d name=%s", wid, name)
        return {"id": wid, "name": row[1], "description": row[2],
                "context": row[3], "brief": row[4] or {}, "created_at": row[5]}

    def list_all(self) -> list[dict[str, Any]]:
        """Return all workspace rows ordered by id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspaces"))
                return [{"id": r[0], "name": r[1], "description": r[2],
                         "context": r[3], "brief": r[4] or {}, "created_at": r[5]}
                        for r in cur.fetchall()]

    def get(self, wid: int) -> dict[str, Any] | None:
        """Return one workspace row by id, or None when it does not exist."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspace_by_id"), (int(wid),))
                row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "description": row[2],
                "context": row[3], "brief": row[4] or {}, "created_at": row[5]}

    def set_context(self, wid: int, context: str) -> dict[str, Any]:
        """Update the free-text context string for workspace wid."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("update_workspace_context"), (context, int(wid)))
                row = cur.fetchone()
        return {"id": row[0], "name": row[1], "description": row[2],
                "context": row[3], "brief": {}, "created_at": row[4]}

    def set_brief(self, wid: int, brief: dict) -> dict[str, Any]:
        """Persist the JSON brief (aim, description, key facts) for workspace wid."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("update_workspace_brief"),
                            (json.dumps(brief or {}), int(wid)))
                row = cur.fetchone()
        logger.info("workspace brief updated id=%s keys=%d", wid, len(brief))
        return {"id": row[0], "name": row[1], "description": row[2],
                "context": row[3], "brief": row[4] or {},
                "created_at": row[5]}

    def get_survivorship(self, wid: int) -> dict[str, Any]:
        """Return the survivorship policy JSON for workspace wid, or {} if unset."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspace_survivorship"), (int(wid),))
                row = cur.fetchone()
        return (row[0] or {}) if row else {}

    def set_survivorship(self, wid: int, policy: dict) -> dict[str, Any]:
        """Persist the survivorship merge policy for workspace wid."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("update_workspace_survivorship"),
                            (json.dumps(policy or {}), int(wid)))
                row = cur.fetchone()
        logger.info("survivorship policy updated ws=%s", wid)
        return {"id": row[0], "survivorship": row[1] or {}}

    def purge_data(self, wid: int) -> dict[str, Any]:
        """Delete all data rows for workspace wid (equivalent to truncating partitions)."""
        wid = int(wid)
        with self._pool.connection() as conn:
            self._drop_partitions_with_conn(conn, wid)
            with conn.cursor() as cur:
                for statement in split_statements(load("purge_workspace_data")):
                    cur.execute(statement, {"wid": wid})
                cur.execute(load("delete_profiles_by_workspace"), (wid,))
                cur.execute(load("delete_tags_by_workspace"), (wid,))
                cur.execute(load("reset_workspace_context"), {"wid": wid})
        logger.info("workspace purged id=%s", wid)
        return {"status": "purged", "workspace_id": wid}

    def nuke(self) -> dict[str, Any]:
        """Factory reset: delete data from all tables, remove non-Default workspaces."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("nuke_system"))
                for statement in split_statements(
                    load("nuke_workspace_partition_data")
                ):
                    cur.execute(statement)
                cur.execute(load("select_non_default_workspace_ids"))
                non_default = cur.fetchall()
                for (wid,) in non_default:
                    self._drop_partitions_with_conn(conn, int(wid))
                cur.execute(load("delete_non_default_workspaces"))
                cur.execute(load("reset_workspace_context"), {"wid": 1})
        logger.info("system nuked — factory reset complete")
        return {"status": "nuked", "workspaces_removed": len(non_default)}

    def delete(self, wid: int) -> None:
        """Delete workspace wid and all its data."""
        if int(wid) == 1:
            raise ValueError("the Default workspace cannot be deleted")
        with self._pool.connection() as conn:
            self._drop_partitions_with_conn(conn, int(wid))
            with conn.cursor() as cur:
                cur.execute(load("delete_profiles_by_workspace"), (wid,))
                cur.execute(load("delete_tags_by_workspace"), (wid,))
                cur.execute(load("delete_runs_by_workspace"), (wid,))
                cur.execute(load("delete_jobs_by_workspace"), (wid,))
                cur.execute(load("delete_workspace_row"), (wid,))
        logger.info("workspace deleted id=%s", wid)
