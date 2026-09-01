"""Workspaces: CRUD + purge/nuke over LIST-partitioned isolated spaces."""
from __future__ import annotations

import logging
from typing import Any

from psycopg import sql
from psycopg.types.json import Json

from aryx.naming import ws_graph  # noqa: F401  re-exported for back-compat
from aryx.queries import load, split_statements
from aryx.store.pool import get_pool

logger = logging.getLogger(__name__)

_PARTITIONED = ["aryx_landed_record", "aryx_entity", "aryx_entity_member", "aryx_relationship"]


def make_workspace_store(dsn: str) -> "WorkspaceStore":
    """Return the appropriate WorkspaceStore for the configured DB backend."""
    from aryx.config import get_settings
    if get_settings().effective_db_backend() == "oci":
        from aryx.store.oracle_workspace import OracleWorkspaceStore
        return OracleWorkspaceStore(dsn)  # type: ignore[return-value]
    return WorkspaceStore(dsn)


class WorkspaceStore:
    """CRUD + purge/nuke over workspaces and their table partitions."""

    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)

    def close(self) -> None:
        """No-op — the shared pool manages connection lifecycle."""
        return None

    @staticmethod
    def _workspace_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "context": row[3],
            "brief": row[4] or {},
            "created_at": row[5],
        }

    def _attach_partitions(self, wid: int) -> None:
        template = load("create_partition")
        with self._pool.connection() as conn:
            for base in _PARTITIONED:
                conn.execute(sql.SQL(template).format(
                    child=sql.Identifier(f"{base}_ws{wid}"),
                    parent=sql.Identifier(base), wid=sql.Literal(wid)))

    def _drop_partitions_with_conn(self, conn: Any, wid: int) -> None:
        template = load("drop_partition")
        for base in _PARTITIONED:
            conn.execute(sql.SQL(template).format(
                child=sql.Identifier(f"{base}_ws{wid}")))

    def _drop_partitions(self, wid: int) -> None:
        with self._pool.connection() as conn:
            self._drop_partitions_with_conn(conn, wid)

    def create(self, name: str, description: str = "", context: str = "",
               brief: dict | None = None) -> dict[str, Any]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("insert_workspace"),
                    (name, description, context, Json(brief or {})),
                )
                row = cur.fetchone()
        wid = int(row[0])
        self._attach_partitions(wid)
        logger.info("workspace created id=%d name=%s", wid, name)
        return self._workspace_dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspaces"))
                return [self._workspace_dict(row) for row in cur.fetchall()]

    def get(self, wid: int) -> dict[str, Any] | None:
        """Return one workspace row by id, or None when it does not exist."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspace_by_id"), (int(wid),))
                row = cur.fetchone()
        return self._workspace_dict(row) if row else None

    def set_context(self, wid: int, context: str) -> dict[str, Any]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("update_workspace_context"), (context, int(wid)))
                row = cur.fetchone()
        return {"id": row[0], "name": row[1], "description": row[2],
                "context": row[3], "brief": {}, "created_at": row[4]}

    def update_metadata(
        self,
        wid: int,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("update_workspace_metadata"),
                    (name, description, int(wid)),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError(f"workspace {wid} not found")
        logger.info("workspace metadata updated id=%s", wid)
        return self._workspace_dict(row)

    def set_brief(self, wid: int, brief: dict) -> dict[str, Any]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("update_workspace_brief"),
                    (Json(brief or {}), int(wid)),
                )
                row = cur.fetchone()
        logger.info("workspace brief updated id=%s keys=%d", wid, len(brief))
        return self._workspace_dict(row)

    def get_survivorship(self, wid: int) -> dict[str, Any]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(load("select_workspace_survivorship"), (int(wid),))
                row = cur.fetchone()
        return (row[0] or {}) if row else {}

    def set_survivorship(self, wid: int, policy: dict) -> dict[str, Any]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("update_workspace_survivorship"),
                    (Json(policy or {}), int(wid)),
                )
                row = cur.fetchone()
        logger.info("survivorship policy updated ws=%s", wid)
        return {"id": row[0], "survivorship": row[1] or {}}

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

    def nuke(self) -> dict[str, Any]:
        """Factory reset: truncate everything, drop non-Default workspaces."""
        with self._pool.connection() as conn:
            conn.execute(load("nuke_system"))
            for base in _PARTITIONED:
                for row in conn.execute(
                    load("select_partition_children"),
                    {"parent": base},
                ).fetchall():
                    # row[0] sourced from pg_inherits catalog — trusted system data,
                    # not user input. sql.Identifier quotes it safely regardless.
                    conn.execute(
                        sql.SQL("TRUNCATE {} CASCADE").format(
                            sql.Identifier(row[0])))
            non_default = conn.execute(
                load("select_non_default_workspace_ids"),
            ).fetchall()
            for (wid,) in non_default:
                self._drop_partitions_with_conn(conn, wid)
            conn.execute(load("delete_non_default_workspaces"))
            conn.execute(load("reset_workspace_context"), {"wid": 1})
        logger.info("system nuked — factory reset complete")
        return {"status": "nuked", "workspaces_removed": len(non_default)}

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
