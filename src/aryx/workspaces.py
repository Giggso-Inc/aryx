"""Workspaces: CRUD + purge/nuke over LIST-partitioned isolated spaces.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`workspaces_crud.py` (`_WorkspaceCrudMixin`) and `workspaces_partitions.py`
(`_WorkspacePartitionsMixin`), both mixed into `WorkspaceStore` here.
`nuke()`/`_drop_partitions_with_conn` stay in the hub as a deliberate
exception: `tests/test_workspaces.py` does
`patch.object(workspaces, "load", ...)`, which only rebinds this module's
own attribute — a function resolving `load` from a different module's
namespace would miss that patch (caught by directly exercising the
patched call, not by grep, since there's no `patch()` string literal for
a plain `patch.object` on a function reference).
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg import sql

from aryx.naming import ws_graph  # noqa: F401  re-exported for back-compat
from aryx.queries import load
from aryx.store.pool import get_pool
from aryx.workspaces_crud import _WorkspaceCrudMixin
from aryx.workspaces_partitions import _PARTITIONED, _WorkspacePartitionsMixin

__all__ = ["WorkspaceStore", "make_workspace_store", "ws_graph"]

logger = logging.getLogger(__name__)


def make_workspace_store(dsn: str) -> "WorkspaceStore":
    """Return the appropriate WorkspaceStore for the configured DB backend."""
    from aryx.config import get_settings
    if get_settings().effective_db_backend() == "oci":
        from aryx.store.oracle_workspace import OracleWorkspaceStore
        return OracleWorkspaceStore(dsn)  # type: ignore[return-value]
    return WorkspaceStore(dsn)


class WorkspaceStore(_WorkspaceCrudMixin, _WorkspacePartitionsMixin):
    """CRUD + purge/nuke over workspaces and their table partitions."""

    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)

    def close(self) -> None:
        """No-op — the shared pool manages connection lifecycle."""
        return None

    def _drop_partitions_with_conn(self, conn: Any, wid: int) -> None:
        template = load("drop_partition")
        for base in _PARTITIONED:
            conn.execute(sql.SQL(template).format(
                child=sql.Identifier(f"{base}_ws{wid}")))

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
