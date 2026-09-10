"""Workspace CRUD (create/list/get/context/metadata/brief/survivorship).

Split out of `workspaces.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from aryx.queries import load

logger = logging.getLogger(__name__)


class _WorkspaceCrudMixin:
    """create / list_all / get / set_context / update_metadata / set_brief /
    get_survivorship / set_survivorship, mixed into WorkspaceStore."""

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
