"""ShayBridgeStore's datasource-sync method (mixin).

Split out of `store/shay_bridge_store.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03). `sync_datasource` calls `DatasourceStore(...)`
directly, and `test_shay_bridge_store.py` patches
`aryx.store.shay_bridge_store.DatasourceStore` — retargeted to
`aryx.store.shay_datasource_bridge.DatasourceStore` since that call now
resolves via this module's own namespace.
"""
from __future__ import annotations

from typing import Any

from aryx.store.datasource_store import DatasourceStore


class _ShayDatasourceBridgeMixin:
    """sync_datasource for ShayBridgeStore."""

    def sync_datasource(
        self,
        *,
        shay_datasource_id: str,
        shay_workspace_id: str,
        name: str,
        kind: str,
        config: dict[str, Any] | None = None,
        secret: str | None = None,
        ingest_job_id: str | None = None,
    ) -> dict[str, Any]:
        mapping = self.get_workspace_mapping(shay_workspace_id)
        if not mapping:
            raise ValueError(f"missing workspace mapping for {shay_workspace_id}")

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT shay_datasource_id::text, aryx_datasource_id, shay_workspace_id::text, aryx_workspace_id, ingest_job_id
                FROM aryx_shay_datasource_map
                WHERE shay_datasource_id = %s::uuid
                """,
                (shay_datasource_id,),
            )
            row = cur.fetchone()
        if row:
            datasource = DatasourceStore(self._dsn).update(
                int(row[1]),
                name=name,
                kind=kind,
                config=config or {},
                secret=secret,
            )
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE aryx_shay_datasource_map
                    SET shay_workspace_id = %s::uuid,
                        aryx_workspace_id = %s,
                        ingest_job_id = %s,
                        updated_at = NOW()
                    WHERE shay_datasource_id = %s::uuid
                    RETURNING shay_datasource_id::text, aryx_datasource_id, shay_workspace_id::text, aryx_workspace_id, ingest_job_id
                    """,
                    (
                        shay_workspace_id,
                        int(mapping["aryx_workspace_id"]),
                        ingest_job_id,
                        shay_datasource_id,
                    ),
                )
                row = cur.fetchone()
            return {
                "shay_datasource_id": row[0],
                "aryx_datasource_id": int(datasource["id"]),
                "shay_workspace_id": row[2],
                "aryx_workspace_id": row[3],
                "ingest_job_id": row[4],
                "created": False,
            }

        datasource = DatasourceStore(self._dsn).add(
            int(mapping["aryx_workspace_id"]),
            name,
            kind,
            config or {},
            secret or "",
        )
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_datasource_map (
                    shay_datasource_id, aryx_datasource_id, shay_workspace_id, aryx_workspace_id, ingest_job_id
                )
                VALUES (%s::uuid, %s, %s::uuid, %s, %s)
                RETURNING shay_datasource_id::text, aryx_datasource_id, shay_workspace_id::text, aryx_workspace_id, ingest_job_id
                """,
                (
                    shay_datasource_id,
                    int(datasource["id"]),
                    shay_workspace_id,
                    int(mapping["aryx_workspace_id"]),
                    ingest_job_id,
                ),
            )
            row = cur.fetchone()
        return {
            "shay_datasource_id": row[0],
            "aryx_datasource_id": row[1],
            "shay_workspace_id": row[2],
            "aryx_workspace_id": row[3],
            "ingest_job_id": row[4],
            "created": True,
        }
