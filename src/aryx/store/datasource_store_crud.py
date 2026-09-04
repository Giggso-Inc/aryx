"""Datasource CRUD (add/list/get/update/delete/ensure), mixed into DatasourceStore.

Split out of `store/datasource_store.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero test patches against this module — confirmed
via grep.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from aryx import datasource_secrets
from aryx.queries import load

logger = logging.getLogger(__name__)


class _DatasourceCrudMixin:
    """add / list / get / update / delete / ensure / _row, mixed into DatasourceStore."""

    def add(self, workspace_id: int, name: str, kind: str,
            config: dict[str, Any], secret: str) -> dict[str, Any]:
        """Encrypt the secret then persist the datasource row.

        config_json is deliberately NOT in insert_datasource.sql's RETURNING
        clause — Oracle's RETURNING...INTO for a native JSON column hits a
        hard ~16KB serialization limit (ORA-40478/JZN-00018), confirmed live
        on a real large XML catalog config. The caller already has `config`
        in Python, so there's no need to round-trip it through the DB at all.
        """
        cipher = datasource_secrets.encrypt(secret)
        mask = datasource_secrets.mask(secret)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("insert_datasource"), {
                "workspace_id": int(workspace_id), "name": name,
                "kind": kind, "config_json": Json(config or {}),
                "secret_cipher": cipher, "secret_mask": mask})
            row = cur.fetchone()
        logger.info("datasource added id=%s ws=%s kind=%s",
                    row[0], workspace_id, kind)
        return {
            "id": row[0], "workspace_id": row[1], "name": row[2],
            "kind": row[3], "config": config or {},
            "secret_mask": row[4], "created_at": row[5],
        }

    def list(self, workspace_id: int) -> list[dict[str, Any]]:
        """List all datasources in a workspace (never returns ciphertext)."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("select_datasources"),
                        {"workspace_id": int(workspace_id)})
            return [self._row(r, omit_cipher=True) for r in cur.fetchall()]

    def get(self, datasource_id: int, workspace_id: int) -> dict[str, Any] | None:
        """Return a single datasource row scoped to workspace_id (callers may decrypt via secret_of)."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("select_datasource_by_id"),
                        {"id": int(datasource_id), "workspace_id": int(workspace_id)})
            row = cur.fetchone()
        if not row:
            return None
        return self._row(row, omit_cipher=True)

    def update(
        self,
        datasource_id: int,
        *,
        name: str,
        kind: str,
        config: dict[str, Any],
        secret: str | None = None,
    ) -> dict[str, Any]:
        """Update datasource metadata and optionally rotate the stored secret."""
        params = {
            "id": int(datasource_id),
            "name": name,
            "kind": kind,
            "config_json": Json(config or {}),
            "secret_cipher": None,
            "secret_mask": None,
        }
        if secret is not None:
            params["secret_cipher"] = datasource_secrets.encrypt(secret)
            params["secret_mask"] = datasource_secrets.mask(secret)
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("update_datasource"), params)
            row = cur.fetchone()
        if not row:
            raise ValueError(f"datasource {datasource_id} not found")
        logger.info("datasource updated id=%s kind=%s", datasource_id, kind)
        # config_json is deliberately not in update_datasource.sql's RETURNING
        # clause either — same ORA-40478/JZN-00018 size limit as add(); use
        # the caller-supplied config directly instead of round-tripping it.
        return {
            "id": row[0], "workspace_id": row[1], "name": row[2],
            "kind": row[3], "config": config or {},
            "secret_mask": row[4], "created_at": row[5],
        }

    def delete(self, datasource_id: int, workspace_id: int) -> None:
        """Hard-delete a datasource and its audit trail (FK cascades), scoped to workspace_id."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("delete_datasource_row"),
                        {"id": int(datasource_id), "workspace_id": int(workspace_id)})
        logger.info("datasource deleted id=%s ws=%s", datasource_id, workspace_id)

    def ensure(self, workspace_id: int, name: str, kind: str) -> dict[str, Any]:
        """Return an existing datasource by (workspace_id, name) or create it."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("select_datasource_by_name"),
                        {"workspace_id": int(workspace_id), "name": name})
            row = cur.fetchone()
        if row:
            return self._row(row, omit_cipher=True)
        try:
            return self.add(workspace_id, name, kind, {}, "")
        except Exception as exc:
            _is_dup = "23505" in str(exc) or "ORA-00001" in str(exc)
            if not _is_dup:
                raise
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(load("select_datasource_by_name"),
                            {"workspace_id": int(workspace_id), "name": name})
                row = cur.fetchone()
            if not row:
                raise
            return self._row(row, omit_cipher=True)

    @staticmethod
    def _row(row: tuple, omit_cipher: bool) -> dict[str, Any]:
        """Project a row tuple to a dict; cipher is never returned over API.

        Two row shapes:
          - 7 cols (insert / list): id, ws, name, kind, config, mask, ts
          - 8 cols (get by id):     id, ws, name, kind, config, cipher, mask, ts
        """
        has_cipher = len(row) >= 8
        mask_idx = 6 if has_cipher else 5
        data = {"id": row[0], "workspace_id": row[1], "name": row[2],
                "kind": row[3], "config": row[4] or {},
                "secret_mask": row[mask_idx], "created_at": row[-1]}
        if not omit_cipher and has_cipher:
            data["secret_cipher"] = row[5]
        return data
