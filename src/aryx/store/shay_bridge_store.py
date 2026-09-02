"""Persistence helpers for Shay-to-Aryx workspace, datasource, and chat bridges."""
from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from aryx.config import get_settings
from aryx.store.datasource_store import DatasourceStore
from aryx.store.pool import get_pool
from aryx.workspaces import make_workspace_store

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
        # No JOIN to gg_workspace — that table is owned by shay-api (cross-service).
        # An INNER JOIN would return None for any mapping whose shay workspace was
        # deleted or not yet visible, causing an unnecessary re-create attempt.
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.shay_workspace_id::text,
                    m.aryx_workspace_id,
                    m.company_id::text,
                    m.sync_state
                FROM aryx_shay_workspace_map m
                WHERE m.shay_workspace_id = %s::uuid
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
            if get_settings().effective_db_backend() == "oci":
                # Postgres's `sync_state || %s::jsonb` is a jsonb shallow-merge
                # (right side wins on key conflicts). _translate_sql() only
                # strips the ::jsonb cast, leaving `||` as Oracle's STRING
                # CONCAT operator -- silently doubling sync_state as text on
                # every repeat call instead of merging it. JSON_MERGEPATCH
                # reproduces the same "patch wins" semantics on Oracle.
                with self._pool.connection() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE aryx_shay_workspace_map
                        SET company_id = COALESCE(%(company_id)s, company_id),
                            sync_state = JSON_MERGEPATCH(sync_state, %(patch)s),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE shay_workspace_id = %(shay_workspace_id)s
                        """,
                        {
                            "company_id": company_id,
                            "patch": Json({"workspace_name": name}),
                            "shay_workspace_id": shay_workspace_id,
                        },
                    )
                updated = self.get_workspace_mapping(shay_workspace_id)
                if not updated:
                    raise RuntimeError(
                        f"bridge UPDATE for {shay_workspace_id!r} left no row behind"
                    )
                updated["created"] = False
                return updated

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

        ws_name = _aryx_workspace_name(name, shay_workspace_id)
        workspace_store = make_workspace_store(self._dsn)
        try:
            aryx_workspace = workspace_store.create(
                ws_name,
                description or f"Bridge for Shay workspace {name}",
                f"shay_workspace_id={shay_workspace_id}",
            )
        except Exception as exc:
            # ORA-00001 / Postgres 23505: workspace was created by a prior attempt
            # that succeeded here but failed on the bridge INSERT (e.g. FK violation).
            # Recover by looking up the orphaned aryx_workspace row by name.
            _is_dup = "ORA-00001" in str(exc) or getattr(exc, "pgcode", None) == "23505"
            if not _is_dup:
                raise
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM aryx_workspace WHERE name = %s",
                    (ws_name,),
                )
                ws_row = cur.fetchone()
            if not ws_row:
                raise
            aryx_workspace = {"id": ws_row[0]}
            logger.info("ensure_workspace_mapping: reusing orphaned workspace id=%s name=%s",
                        ws_row[0], ws_name)
        finally:
            workspace_store.close()

        if get_settings().effective_db_backend() == "oci":
            # Oracle has no ON CONFLICT ... DO UPDATE; _translate_sql() raises
            # loudly on that construct rather than silently degrading (post-merge
            # review fix), so this caller needs an explicit MERGE instead of the
            # Postgres upsert below. Same COALESCE-on-conflict semantics: an
            # existing row's company_id is only overwritten when the new value
            # is non-null.
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    MERGE INTO aryx_shay_workspace_map dst
                    USING (SELECT 1 AS dual_row FROM dual) src
                    ON (dst.shay_workspace_id = %(shay_workspace_id)s)
                    WHEN MATCHED THEN UPDATE SET
                        company_id = COALESCE(%(company_id)s, dst.company_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHEN NOT MATCHED THEN INSERT (
                        shay_workspace_id, aryx_workspace_id, company_id, sync_state
                    ) VALUES (
                        %(shay_workspace_id)s, %(aryx_workspace_id)s,
                        %(company_id)s, %(sync_state)s
                    )
                    """,
                    {
                        # named params (not a positional tuple) so oracle_pool's
                        # ON-clause CLOB-exclusion regex can find %(shay_workspace_id)s
                        # literally inside ON(...) and keep it VARCHAR2 -- the
                        # positional-tuple path ignores that exclusion entirely
                        # and would otherwise CLOB-coerce it, raising ORA-22848
                        # ("cannot use CLOB type as comparison key").
                        "shay_workspace_id": shay_workspace_id,
                        "aryx_workspace_id": int(aryx_workspace["id"]),
                        "company_id": company_id,
                        "sync_state": Json({"workspace_name": name}),
                    },
                )
            created_row = self.get_workspace_mapping(shay_workspace_id)
            if created_row:
                # get_workspace_mapping() found no row for this id at function
                # entry (line 67 above), so this MERGE always took the "WHEN
                # NOT MATCHED THEN INSERT" branch -- a genuine new row.
                created_row["created"] = True
                return created_row
            raise RuntimeError(
                f"bridge MERGE for {shay_workspace_id!r} left no row behind"
            )

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

        if row is None:
            # Should not happen on Postgres (RETURNING always yields a row on
            # both INSERT and DO UPDATE) -- defensive fallback only.
            existing = self.get_workspace_mapping(shay_workspace_id)
            if existing:
                existing["created"] = False
                return existing
            raise RuntimeError(
                f"bridge INSERT for {shay_workspace_id!r} silently failed and no row found"
            )
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

        if get_settings().effective_db_backend() == "oci":
            # Same class of bug as ensure_workspace_mapping() above: Oracle has
            # no ON CONFLICT ... DO UPDATE, so this needs an explicit MERGE.
            # Unlike that method, this upsert is a plain full-field overwrite
            # (no COALESCE/JSON-merge semantics), so the MERGE is simpler.
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM aryx_shay_chat_map WHERE shay_thread_id = %(shay_thread_id)s",
                    {"shay_thread_id": shay_thread_id},
                )
                pre_existing = cur.fetchone() is not None
                cur.execute(
                    """
                    MERGE INTO aryx_shay_chat_map dst
                    USING (SELECT 1 AS dual_row FROM dual) src
                    ON (dst.shay_thread_id = %(shay_thread_id)s)
                    WHEN MATCHED THEN UPDATE SET
                        aryx_workspace_id = %(aryx_workspace_id)s,
                        shay_workspace_id = %(shay_workspace_id)s,
                        ask_session_key = %(ask_session_key)s,
                        updated_at = CURRENT_TIMESTAMP
                    WHEN NOT MATCHED THEN INSERT (
                        shay_thread_id, aryx_workspace_id, shay_workspace_id, ask_session_key
                    ) VALUES (
                        %(shay_thread_id)s, %(aryx_workspace_id)s,
                        %(shay_workspace_id)s, %(ask_session_key)s
                    )
                    """,
                    {
                        "shay_thread_id": shay_thread_id,
                        "aryx_workspace_id": int(aryx_workspace_id),
                        "shay_workspace_id": shay_workspace_id,
                        "ask_session_key": ask_session_key,
                    },
                )
                cur.execute(
                    "SELECT shay_thread_id, aryx_workspace_id, shay_workspace_id, ask_session_key"
                    " FROM aryx_shay_chat_map WHERE shay_thread_id = %(shay_thread_id)s",
                    {"shay_thread_id": shay_thread_id},
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"chat map MERGE for {shay_thread_id!r} left no row behind")
            return {
                "shay_thread_id": row[0],
                "aryx_workspace_id": row[1],
                "shay_workspace_id": row[2],
                "ask_session_key": row[3],
                "created": not pre_existing,
            }

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
        if row is None:
            # Should not happen on Postgres (RETURNING always yields a row on
            # both INSERT and DO UPDATE) -- defensive fallback only.
            with self._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT shay_thread_id::text, aryx_workspace_id, shay_workspace_id::text, ask_session_key"
                    " FROM aryx_shay_chat_map WHERE shay_thread_id = %s::uuid",
                    (shay_thread_id,),
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"chat map INSERT for {shay_thread_id!r} silently failed and no row found")
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
    return ShayBridgeStore(get_settings().effective_dsn())
