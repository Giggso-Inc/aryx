"""Persistence helpers for Shay-to-Aryx workspace, datasource, and chat bridges."""
from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.store.datasource_store import DatasourceStore
from aryx.store.pool import get_pool
from aryx.workspaces import WorkspaceStore

logger = logging.getLogger(__name__)


def _aryx_workspace_name(name: str, shay_workspace_id: str) -> str:
    label = (name or "Workspace").strip() or "Workspace"
    return f"shay::{label}::{shay_workspace_id[:8]}"


class ShayBridgeStore:
    """CRUD over Shay bridge tables backed by the Aryx Postgres."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = get_pool(dsn)

    def close(self) -> None:
        """No-op: shared pool lifecycle is managed globally."""

    def get_workspace_mapping(self, shay_workspace_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    aryx_shay_workspace_map.shay_workspace_id::text,
                    aryx_shay_workspace_map.aryx_workspace_id,
                    aryx_shay_workspace_map.company_id::text,
                    aryx_shay_workspace_map.sync_state
                FROM aryx_shay_workspace_map
                JOIN gg_workspace ON gg_workspace.id = aryx_shay_workspace_map.shay_workspace_id
                JOIN aryx_workspace ON aryx_workspace.id = aryx_shay_workspace_map.aryx_workspace_id
                WHERE aryx_shay_workspace_map.shay_workspace_id = %s::uuid
                """,
                (shay_workspace_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "shay_workspace_id": row[0],
            "aryx_workspace_id": row[1],
            "company_id": row[2],
            "sync_state": row[3] or {},
        }

    def ensure_workspace_mapping(
        self,
        *,
        shay_workspace_id: str,
        name: str,
        description: str = "",
        company_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_workspace_mapping(shay_workspace_id)
        if existing:
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE aryx_shay_workspace_map
                    SET company_id = COALESCE(%s::uuid, company_id),
                        sync_state = sync_state || %s::jsonb,
                        updated_at = NOW()
                    WHERE shay_workspace_id = %s::uuid
                    RETURNING shay_workspace_id::text, aryx_workspace_id, company_id::text, sync_state
                    """,
                    (
                        company_id,
                        Json({"workspace_name": name}),
                        shay_workspace_id,
                    ),
                )
                row = cur.fetchone()
            return {
                "shay_workspace_id": row[0],
                "aryx_workspace_id": row[1],
                "company_id": row[2],
                "sync_state": row[3] or {},
                "created": False,
            }

        workspace_store = WorkspaceStore(self._dsn)
        try:
            aryx_workspace = workspace_store.create(
                _aryx_workspace_name(name, shay_workspace_id),
                description or f"Bridge for Shay workspace {name}",
                f"shay_workspace_id={shay_workspace_id}",
            )
        finally:
            workspace_store.close()

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_workspace_map (
                    shay_workspace_id, aryx_workspace_id, company_id, sync_state
                )
                VALUES (%s::uuid, %s, %s::uuid, %s)
                ON CONFLICT (shay_workspace_id) DO UPDATE
                SET company_id = COALESCE(EXCLUDED.company_id, aryx_shay_workspace_map.company_id),
                    updated_at = NOW()
                RETURNING shay_workspace_id::text, aryx_workspace_id, company_id::text, sync_state
                """,
                (
                    shay_workspace_id,
                    int(aryx_workspace["id"]),
                    company_id,
                    Json({"workspace_name": name}),
                ),
            )
            row = cur.fetchone()
        return {
            "shay_workspace_id": row[0],
            "aryx_workspace_id": row[1],
            "company_id": row[2],
            "sync_state": row[3] or {},
            "created": True,
        }

    def ensure_chat_mapping(
        self,
        *,
        shay_thread_id: str,
        shay_workspace_id: str,
        aryx_workspace_id: int,
        ask_session_key: str | None = None,
    ) -> dict[str, Any]:
        ask_session_key = ask_session_key or shay_thread_id
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_chat_map (
                    shay_thread_id, aryx_workspace_id, shay_workspace_id, ask_session_key
                )
                VALUES (%s::uuid, %s, %s::uuid, %s)
                ON CONFLICT (shay_thread_id) DO UPDATE
                SET aryx_workspace_id = EXCLUDED.aryx_workspace_id,
                    shay_workspace_id = EXCLUDED.shay_workspace_id,
                    ask_session_key = EXCLUDED.ask_session_key,
                    updated_at = NOW()
                RETURNING shay_thread_id::text, aryx_workspace_id, shay_workspace_id::text, ask_session_key
                """,
                (shay_thread_id, int(aryx_workspace_id), shay_workspace_id, ask_session_key),
            )
            row = cur.fetchone()
        return {
            "shay_thread_id": row[0],
            "aryx_workspace_id": row[1],
            "shay_workspace_id": row[2],
            "ask_session_key": row[3],
            "created": True,
        }

    def append_chat_turn(
        self,
        *,
        shay_thread_id: str,
        aryx_workspace_id: int,
        question: str,
        answer: str,
        citations: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        grounding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO aryx_shay_chat_turn (
                    shay_thread_id, aryx_workspace_id, question, answer, citations, usage, grounding
                )
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    shay_thread_id,
                    int(aryx_workspace_id),
                    question,
                    answer,
                    Json(citations or []),
                    Json(usage or {}),
                    Json(grounding or {}),
                ),
            )
            row = cur.fetchone()
        return {"id": row[0], "created_at": row[1]}

    def list_chat_turns(self, shay_thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, shay_thread_id::text, aryx_workspace_id, question, answer, citations, usage, grounding, created_at
                FROM aryx_shay_chat_turn
                WHERE shay_thread_id = %s::uuid
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (shay_thread_id, int(limit)),
            )
            rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "shay_thread_id": row[1],
                "aryx_workspace_id": row[2],
                "question": row[3],
                "answer": row[4],
                "citations": row[5] or [],
                "usage": row[6] or {},
                "grounding": row[7] or {},
                "created_at": row[8],
            }
            for row in rows
        ]

    def list_workspace_threads(
        self,
        shay_workspace_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.shay_thread_id::text,
                    m.aryx_workspace_id,
                    m.ask_session_key,
                    COALESCE(MAX(t.created_at), m.updated_at) AS updated_at,
                    COALESCE(
                        (
                            SELECT question
                            FROM aryx_shay_chat_turn
                            WHERE shay_thread_id = m.shay_thread_id
                            ORDER BY created_at ASC
                            LIMIT 1
                        ),
                        'New chat'
                    ) AS title,
                    COUNT(t.id) AS turn_count
                FROM aryx_shay_chat_map m
                LEFT JOIN aryx_shay_chat_turn t
                    ON t.shay_thread_id = m.shay_thread_id
                WHERE m.shay_workspace_id = %s::uuid
                GROUP BY m.shay_thread_id, m.aryx_workspace_id, m.ask_session_key, m.updated_at
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (shay_workspace_id, int(limit)),
            )
            rows = cur.fetchall()
        return [
            {
                "shay_thread_id": row[0],
                "aryx_workspace_id": row[1],
                "ask_session_key": row[2],
                "updated_at": row[3],
                "title": row[4],
                "turn_count": row[5],
            }
            for row in rows
        ]

    def conversation_history(self, shay_thread_id: str, limit_pairs: int = 6) -> list[dict[str, str]]:
        pair_limit = max(int(limit_pairs), 1)
        turns = self.list_chat_turns(shay_thread_id, limit=pair_limit)
        history: list[dict[str, str]] = []
        for turn in turns:
            history.append({"role": "user", "text": turn["question"]})
            history.append({"role": "assistant", "text": turn["answer"]})
        return history

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


def get_shay_bridge_store() -> ShayBridgeStore:
    """Return a store bound to the configured Aryx relational DSN."""
    return ShayBridgeStore(get_settings().rdb_dsn)
