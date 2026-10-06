"""Oracle ADB 26ai workspace store — replaces psycopg.connect() with oracledb.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03),
`_parse_brief` moved to `oracle_workspace_helpers.py` (zero patch risk).
The `OracleWorkspaceStore` class stays as a deliberate, documented
exception: `load` is directly whitebox-patched
(`aryx.store.oracle_workspace.load`) across ~30 test cases in
`tests/test_oracle_workspace.py`, and nearly every method calls it —
moving any one out would mean it could no longer see the patch (the same
bound-at-import-time gotcha this plan has hit repeatedly).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.queries import load
from aryx.store.oracle_pool import OracleConnectionWrapper, get_oracle_pool
from aryx.store.oracle_workspace_helpers import _parse_brief
from aryx.raven_log import raven_log

logger = logging.getLogger(__name__)


# Tables that used Postgres partitioning; on Oracle we use plain tables with
# workspace_id as an indexed column — no partition DDL needed.
_PARTITIONED = ["aryx_landed_record", "aryx_entity", "aryx_entity_member", "aryx_relationship"]

# Pre-built at module load time from the constant above.
# Oracle identifiers (table names) cannot be passed as bind variables, so
# interpolation is unavoidable — building here keeps f-strings away from execute().
#
# Bounded by ROWNUM, not a single unbounded DELETE: confirmed live,
# 2026-10-07 -- a workspace can carry millions of rows in one of these
# tables (aryx_relationship specifically: 2.55M rows for a workspace with
# zero aryx_entity rows, i.e. orphaned relationship data) even when a
# workspace_id-leading index already exists. An index fixes a full-table-
# scan; it does nothing for the sheer cost of physically deleting millions
# of rows (undo/redo + index maintenance per row) in one statement, which
# took 437s in that case -- far past the 30s Oracle call_timeout that a
# real admin-API request runs under (DPY-4024/ORA-03156). Batching keeps
# every individual DELETE well under that timeout regardless of how much
# data a workspace turns out to have.
_DELETE_BATCH_SIZE = 50_000
_DELETE_PARTITION_SQLS = {
    t: f"DELETE FROM {t} WHERE workspace_id = :1 AND ROWNUM <= :2" for t in _PARTITIONED
}
_TRUNCATE_SQLS = {t: f"DELETE FROM {t}" for t in _PARTITIONED}


def _csv_purge_failed(step: str, wid: int | None, exc: BaseException) -> None:
    """WARN for one skipped best-effort CSV cleanup step of a workspace purge."""
    raven_log("WARN", "P3", f"workspace.purge.csv_{step}_skipped cleanup step failed, purge continues",
              error_code="ARYX_WS_CSV_PURGE_SKIPPED",
              context={"workspace_id": wid, "step": step, "triggering_error": type(exc).__name__,
                       "attempt": 1, "max_attempts": 1, "backoff_ms": 0, "recovery_selected": "skip_step",
                       "fallback_target": None, "exit_condition": "skipped", "result": "skipped"})


class OracleWorkspaceStore:
    """WorkspaceStore backed by Oracle ADB 26ai via oracledb.

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
        """Delete all rows for workspace wid from the four core tables, in
        bounded batches of _DELETE_BATCH_SIZE rows per statement.

        Each batch is its own connection/transaction (acquire, execute,
        commit-on-exit via self._pool.connection()) rather than one
        connection held open for the whole table -- so a workspace with
        millions of rows in one table never risks a single DELETE
        exceeding Oracle's call_timeout (confirmed live, 2026-10-07: see
        _DELETE_PARTITION_SQLS' docstring above for the incident that
        prompted this)."""
        for table in _PARTITIONED:
            sql = _DELETE_PARTITION_SQLS[table]
            while True:
                with self._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, (wid, _DELETE_BATCH_SIZE))
                        deleted = cur.rowcount
                if deleted < _DELETE_BATCH_SIZE:
                    break

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
                "context": row[3], "brief": _parse_brief(row[4]), "created_at": row[5]}

    def list_all(self) -> list[dict[str, Any]]:
        """Return all workspace rows ordered by id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspaces"))
                rows = cur.fetchall()
        logger.debug("list_all: fetched %d workspace rows", len(rows))
        for r in rows:
            logger.debug("list_all: ws id=%s brief col type=%s value=%r",
                         r[0], type(r[4]).__name__, r[4])
        return [{"id": r[0], "name": r[1], "description": r[2],
                 "context": r[3], "brief": _parse_brief(r[4]), "created_at": r[5]}
                for r in rows]

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
                "context": row[3], "brief": _parse_brief(None), "created_at": row[4]}

    def set_brief(self, wid: int, brief: dict) -> dict[str, Any]:
        """Persist the JSON brief (aim, description, key facts) for workspace wid."""
        logger.info("set_brief: wid=%s input_keys=%s", wid,
                    list(brief.keys()) if isinstance(brief, dict) else repr(brief))
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("update_workspace_brief"),
                            (json.dumps(brief or {}), int(wid)))
                row = cur.fetchone()
        logger.info("set_brief: RETURNING row col types=%s",
                    [type(c).__name__ for c in row] if row else None)
        logger.info("set_brief: RETURNING brief (row[4]) type=%s",
                    type(row[4]).__name__ if row else "no-row")
        logger.debug("set_brief: RETURNING brief (row[4]) value=%r",
                     row[4] if row else None)
        logger.info("workspace brief updated id=%s keys=%d", wid, len(brief or {}))
        return {"id": row[0], "name": row[1], "description": row[2],
                "context": row[3], "brief": _parse_brief(row[4]),
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

    def _purge_csv_issues(self, wid: int | None, whole_workspace: bool = False) -> None:
        """Stored CSV ingestion issues (rejected rows, kept files) and the workspace's own
        ``ws<id>_…`` data tables go with the workspace.

        Best effort, each step in its own transaction: if a table does not exist (migration 0047/0048 not
        applied) or a drop fails, this logs and carries on — it must never make a workspace purge/delete fail.
        """
        try:
            from aryx.csv_bml_ingestion.issue_store import purge_issues  # noqa: PLC0415

            purge_issues(self._pool.connection, wid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("csv ingest issue cleanup skipped (wid=%s)", wid, exc_info=True)
            _csv_purge_failed("issues", wid, exc)
        try:
            from aryx.csv_bml_ingestion.workspace_tables import drop_workspace_tables  # noqa: PLC0415

            drop_workspace_tables(self._pool.connection, wid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("csv ingest workspace tables cleanup skipped (wid=%s)", wid, exc_info=True)
            _csv_purge_failed("tables", wid, exc)
        try:
            from aryx.csv_bml_ingestion.workspace_tables import remove_workspace_files  # noqa: PLC0415

            remove_workspace_files(wid, whole_workspace=whole_workspace)
        except Exception as exc:  # noqa: BLE001
            logger.warning("csv ingest rejected-rows file cleanup skipped (wid=%s)", wid, exc_info=True)
            _csv_purge_failed("files", wid, exc)

    def purge_data(self, wid: int) -> dict[str, Any]:
        """Delete all data rows for workspace wid (equivalent to truncating partitions)."""
        wid = int(wid)
        self._drop_partitions(wid)
        stmts = load("purge_workspace_data")
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                for stmt in stmts.split(";"):
                    stmt = stmt.strip()
                    if stmt and not stmt.startswith("--"):
                        cur.execute(stmt, {"wid": wid})
                cur.execute(load("delete_profiles_by_workspace"), (wid,))
                cur.execute(load("delete_tags_by_workspace"), (wid,))
                cur.execute(load("reset_workspace_context"), {"wid": wid})
        self._purge_csv_issues(wid)
        logger.info("workspace purged id=%s", wid)
        return {"status": "purged", "workspace_id": wid}

    def nuke(self) -> dict[str, Any]:
        """Factory reset: delete data from all tables, remove non-Default workspaces."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("nuke_system"))
                for table in _PARTITIONED:
                    cur.execute(_TRUNCATE_SQLS[table])
                cur.execute(load("select_non_default_workspace_ids"))
                non_default = cur.fetchall()
                for (wid,) in non_default:
                    self._drop_partitions(int(wid))
                cur.execute(load("delete_non_default_workspaces"))
                cur.execute(load("reset_workspace_context"), {"wid": 1})
        self._purge_csv_issues(None, whole_workspace=True)
        logger.info("system nuked — factory reset complete")
        # workspace_ids: see workspaces/__init__.py's WorkspaceStore.nuke()
        # sibling method for why this additive field exists (CPQ_Hardcode_
        # Audit_dev_oci_2026-09-25.md T11) -- kept consistent across both
        # backends.
        return {
            "status": "nuked", "workspaces_removed": len(non_default),
            "workspace_ids": [int(wid) for (wid,) in non_default],
        }

    def delete(self, wid: int) -> None:
        """Delete workspace wid and all its data."""
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
        self._purge_csv_issues(wid, whole_workspace=True)
        logger.info("workspace deleted id=%s", wid)
